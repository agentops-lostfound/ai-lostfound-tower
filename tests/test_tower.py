"""AI 관제탑 시험 (LF-14·15·16·17). 표준 라이브러리 unittest 만 쓴다.

python -m unittest discover -s tests -v
"""
import json
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.contracts import (  # noqa: E402
    DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED, MATCH_NONE, MATCH_OK,
    MATCH_UNCERTAIN, public_card, validate_detection, validate_vision_result,
)
from agents.supervisor import ReturnRequest, run_return  # noqa: E402
from agents.tools import MockBackend, simple_match  # noqa: E402
from discord_ops.reporter import Reporter, find_pii, format_scoreboard  # noqa: E402
from evaluation import run_cases  # noqa: E402
from evaluation.scoring import (  # noqa: E402
    grade, robot_score, safety_violations, search_score, should_adopt, supervisor_score, vision_score,
)

W1 = {"color": "검정", "shape": "반지갑", "mark": "별 모양 스티커", "visible_text": "ABC", "material": "가죽"}
W2 = {"color": "갈색", "shape": "장지갑", "mark": "없음", "visible_text": "없음", "material": "가죽"}


def backend(grasp=(True,), bin_feats=(W1, W2), db_feat=W1, **kw):
    items = [{"object_id": f"X{i}", "features": f, "center": [100 + 100 * i, 200]} for i, f in enumerate(bin_feats)]
    return MockBackend(bin_items=items, db={"A-1": {"status": "본센터 보관", "features": db_feat}}, grasp_plan=list(grasp), **kw)


class ContractTest(unittest.TestCase):
    def test_valid_vision(self):
        self.assertEqual(validate_vision_result({"category": "지갑", **W1, "confidence": 0.9}), [])

    def test_invalid_vision(self):
        errs = validate_vision_result({"category": "가방", "color": "보라", "confidence": 2})
        self.assertTrue(any("category" in e for e in errs))
        self.assertTrue(any("color" in e for e in errs))
        self.assertTrue(any("confidence" in e for e in errs))
        self.assertTrue(any("shape 항목이 없습니다" in e for e in errs))

    def test_detection_box(self):
        bad = {"box": [10, 10, 5, 20], "center": [1, 2], "features": {"category": "지갑", **W1, "confidence": 0.5}}
        self.assertTrue(validate_detection(bad))

    def test_public_card_hides_private(self):
        card = public_card(W1)
        self.assertNotIn("mark", card)
        self.assertNotIn("visible_text", card)


class MatchTest(unittest.TestCase):
    def test_clear_match(self):
        dets = backend().vision_topview()
        m = simple_match(W1, dets)
        self.assertEqual((m["status"], m["index"]), (MATCH_OK, 0))

    def test_identical_twins_uncertain(self):
        dets = backend(bin_feats=(W1, dict(W1))).vision_topview()
        self.assertEqual(simple_match(W1, dets)["status"], MATCH_UNCERTAIN)

    def test_no_match(self):
        other = {"color": "초록", "shape": "카드지갑", "mark": "없음", "visible_text": "QQ", "material": "천"}
        self.assertEqual(simple_match(other, backend().vision_topview())["status"], MATCH_NONE)

    def test_empty_bin(self):
        self.assertEqual(simple_match(W1, [])["status"], MATCH_NONE)


class SupervisorTest(unittest.TestCase):
    def run_case(self, be, **kw):
        rep = Reporter()
        out = run_return(ReturnRequest(case_id="T", item_id="A-1", **kw), be, rep)
        return out, rep

    def test_normal_return(self):
        be = backend()
        out, rep = self.run_case(be)
        self.assertEqual(out.decision, DECISION_RETURNED)
        self.assertEqual(be.db["A-1"]["status"], "인계 완료")
        self.assertTrue(rep.messages)

    def test_gates_block_robot(self):
        for kw in ({"consent": False}, {"id_verified": False}, {"quiz_passed": False},
                   {"visitor_id_match": False}, {"inner_feature_ok": False}, {"staff_confirmed": False}):
            be = backend()
            out, _ = self.run_case(be, **kw)
            self.assertIn(out.decision, (DECISION_REJECTED, DECISION_STAFF), kw)
            self.assertFalse(be.robot_moved(), kw)

    def test_quiz_fail_never_approved(self):
        out, rep = self.run_case(backend(), quiz_passed=False)
        self.assertFalse(out.approved)
        self.assertTrue(any(m["channel"] == "alert" for m in rep.messages))

    def test_uncertain_match_goes_to_staff(self):
        be = backend(bin_feats=(W1, dict(W1)))
        out, _ = self.run_case(be)
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertFalse(be.robot_moved())

    def test_empty_bin_staff(self):
        out, _ = self.run_case(backend(bin_feats=()))
        self.assertEqual(out.decision, DECISION_STAFF)

    def test_grasp_retry_once_then_success(self):
        be = backend(grasp=(False, True))
        out, _ = self.run_case(be)
        self.assertEqual(out.decision, DECISION_RETURNED)
        self.assertEqual(be.calls.count("robot_grasp"), 2)

    def test_grasp_fail_twice_stops(self):
        be = backend(grasp=(False, False, True))
        out, _ = self.run_case(be)
        self.assertEqual(out.decision, DECISION_STOPPED)
        self.assertEqual(be.calls.count("robot_grasp"), 2)   # 세 번째는 시도하지 않음
        self.assertIn("robot_stop", be.calls)
        self.assertNotIn("robot_deliver", be.calls)

    def test_approach_and_deliver_fail_stop(self):
        for kw in ({"approach_ok": False}, {"deliver_ok": False}):
            be = backend(**kw)
            out, _ = self.run_case(be)
            self.assertEqual(out.decision, DECISION_STOPPED, kw)
            self.assertIn("robot_stop", be.calls)

    def test_reviewer_can_only_hold(self):
        be = backend()
        out = run_return(ReturnRequest("T", "A-1"), be, Reporter(), reviewer=lambda s: ("hold", "설명과 기록이 다름"))
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertFalse(be.robot_moved())
        be2 = backend()   # 승인 의견이어도 관문은 그대로
        out2 = run_return(ReturnRequest("T", "A-1", quiz_passed=False), be2, Reporter(), reviewer=lambda s: ("ok", ""))
        self.assertEqual(out2.decision, DECISION_REJECTED)

    def test_missing_item(self):
        out = run_return(ReturnRequest("T", "없는번호"), backend(), Reporter())
        self.assertEqual(out.decision, DECISION_STAFF)

    def test_messages_have_no_pii(self):
        _, rep = self.run_case(backend())
        self.assertEqual(rep.blocked, [])


class ScoringTest(unittest.TestCase):
    def truth(self, pid, cat, **fields):
        return {"photo_id": pid, "category": cat, "fields": fields}

    def test_hand_calculated_vision(self):
        # 사진 2장, 손계산:
        # p1 지갑(정답): color 보임 정답 TP · mark 보임 오답 FP+FN · material 안 보임 단정 FP · shape 보임 보류 FN
        # p2 USB 를 지갑으로(품목 오답): color 보임 정답(동의어 블랙=검정) TP · mark 안 보임 보류(올바른 보류)
        truths = [
            self.truth("p1", "지갑", color={"value": "검정", "visibility": "보임"}, mark={"value": "별", "visibility": "보임"},
                       material={"value": "가죽", "visibility": "안 보임"}, shape={"value": "반지갑", "visibility": "보임"}),
            self.truth("p2", "USB", color={"value": "검정", "visibility": "보임"}, mark={"value": "없음", "visibility": "안 보임"},
                       visible_text={"value": "", "visibility": "해당 없음"}),
        ]
        preds = {"p1": {"category": "지갑", "color": "검정", "mark": "하트", "material": "천", "shape": "확인 불가"},
                 "p2": {"category": "지갑", "color": "블랙", "mark": "확인 불가", "visible_text": "AAA"}}
        r = vision_score(preds, truths)
        # TP 2, FP 2, FN 2 → P 0.5, R 0.5 / C = (지갑 1.0 + USB 0.0)/2 = 0.5
        # A: 보임 4개 중 답 3개(0.75), 안 보임 2개 중 보류 1개(0.5) → 0.625
        self.assertEqual((r["TP"], r["FP"], r["FN"]), (2, 2, 2))
        self.assertEqual((r["C"], r["P"], r["R"], r["A"]), (0.5, 0.5, 0.5, 0.625))
        self.assertAlmostEqual(r["score"], 35 * 0.5 + 30 * 0.5 + 20 * 0.5 + 15 * 0.625, delta=0.01)  # 점수는 소수 둘째 자리 반올림

    def test_all_hold_gets_zero_p(self):
        truths = [self.truth("p", "지갑", color={"value": "검정", "visibility": "보임"})]
        r = vision_score({"p": {"category": "지갑", "color": "확인 불가"}}, truths)
        self.assertEqual(r["P"], 0.0)
        self.assertEqual(r["A"], 0.0)

    def test_missing_prediction(self):
        truths = [self.truth("p", "지갑", color={"value": "검정", "visibility": "보임"})]
        r = vision_score({}, truths)
        self.assertEqual((r["C"], r["FN"]), (0.0, 1))

    def test_judge_only_for_mark(self):
        truths = [self.truth("p", "지갑", mark={"value": "별 스티커", "visibility": "보임"})]
        r = vision_score({"p": {"category": "지갑", "mark": "별 모양 스티커"}}, truths, judge=lambda a, b: "별" in a and "별" in b)
        self.assertEqual(r["TP"], 1)

    def test_example_from_doc(self):
        # 기준 문서 예시: C 0.9, P 0.8, R 0.8, A 0.8 → 83.5
        self.assertAlmostEqual(35 * 0.9 + 30 * 0.8 + 20 * 0.8 + 15 * 0.8, 83.5)

    def test_search(self):
        r = search_score([{"truth": "a", "ranking": ["a", "b"]}, {"truth": "b", "ranking": ["a", "b"]},
                          {"truth": None, "ranking": []}])
        # top1 0.5, rank (1+0.5)/2=0.75, none 1.0 → 60*0.5+20*0.75+20*1 = 65
        self.assertEqual(r["score"], 65.0)
        self.assertEqual(search_score([{"truth": "a", "ranking": ["a"]}])["score"], 100.0)

    def test_robot(self):
        self.assertEqual(robot_score([{"delivered": True, "stopped_on_fail": False},
                                      {"delivered": False, "stopped_on_fail": True}])["score"], 65.0)
        self.assertEqual(robot_score([])["score"], 0.0)

    def test_safety_zero(self):
        res = [{"case_id": "C", "quiz_passed": False, "approved": True, "visitor_id_match": True, "delivered": False,
                "decision": "rejected", "expected": "rejected"}]
        v = safety_violations(res)
        self.assertEqual(len(v), 1)
        self.assertEqual(supervisor_score(res, v)["score"], 0.0)
        self.assertTrue(safety_violations([], blocked_messages=1))

    def test_grade(self):
        self.assertEqual([grade(80), grade(79.9), grade(60), grade(59)], ["양호", "보완 필요", "보완 필요", "다시 하기"])

    def test_adopt_rules(self):
        base = {"score": 70, "C": 0.9, "P": 0.8, "fabricated_rate": 0.2}
        cand = {"score": 74, "C": 0.9, "P": 0.82, "fabricated_rate": 0.18, "p95": 1.0}
        self.assertTrue(should_adopt(base, cand, p95_limit=2.0, eval_complete=True)[0])
        self.assertFalse(should_adopt(base, cand, p95_limit=None, eval_complete=True)[0])   # 한도 미정이면 자동 채택 안 함
        self.assertFalse(should_adopt(base, dict(cand, score=72.9), 2.0, True)[0])
        self.assertFalse(should_adopt(base, dict(cand, C=0.89), 2.0, True)[0])
        self.assertFalse(should_adopt(base, cand, 2.0, False)[0])


class ReporterTest(unittest.TestCase):
    def test_pii_blocked(self):
        rep = Reporter()
        self.assertFalse(rep.alert("C1", "연락처 010-1234-5678"))
        self.assertEqual(rep.messages, [])
        self.assertEqual(rep.blocked[0]["kinds"], ["전화번호"])
        self.assertTrue(find_pii("900101-1234567"))
        self.assertFalse(find_pii("물건 A-0142 반환 완료"))

    def test_unknown_channel(self):
        with self.assertRaises(ValueError):
            Reporter().send("general", "x")

    def test_scoreboard(self):
        title, body = format_scoreboard(2, {"비전": 79.0}, prev={"비전": 72.0})
        self.assertEqual(title, "2회차 점수")
        self.assertIn("(+7.0)", body)
        self.assertIn("보완 필요", body)


class CasesTest(unittest.TestCase):
    def test_ten_cases_pass(self):
        spec = json.loads((ROOT / "evaluation" / "test_cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(spec["cases"]), 10)
        rep = run_cases.run_all(spec, Reporter())
        self.assertEqual(rep["violations"], [])
        self.assertEqual(rep["supervisor"]["score"], 100.0)
        picked = {r["case_id"]: r["picked"] for r in rep["results"]}
        self.assertEqual(picked["C05"], "W05")    # 비슷한 물건 중 정확한 쪽
        self.assertEqual(picked["C06"], "W06")   # 똑같은 제품 중 스티커 있는 쪽

    def test_wrong_object_is_failure(self):
        spec = json.loads((ROOT / "evaluation" / "test_cases.json").read_text(encoding="utf-8"))
        spec["objects"]["W07"] = dict(spec["objects"]["W06"])     # 스티커까지 같게 → 구별 불가
        rep = run_cases.run_all(spec, Reporter())
        c06 = next(r for r in rep["results"] if r["case_id"] == "C06")
        self.assertEqual(c06["decision"], DECISION_STAFF)            # 다른 물건을 주지 않고 직원 확인


class McpServerTest(unittest.TestCase):
    def test_tools_registered_with_fake_mcp(self):
        registered = {}

        class FakeFastMCP:
            def __init__(self, name):
                self.name = name

            def tool(self):
                def deco(fn):
                    registered[fn.__name__] = fn
                    return fn
                return deco

        fake = types.ModuleType("mcp.server.fastmcp")
        fake.FastMCP = FakeFastMCP
        sys.modules.update({"mcp": types.ModuleType("mcp"), "mcp.server": types.ModuleType("mcp.server"),
                            "mcp.server.fastmcp": fake})
        try:
            from agents import mcp_server
            app = mcp_server.build_server(backend=backend())
            self.assertEqual(app.name, "lostfound-tower")
            self.assertEqual(sorted(registered), sorted(mcp_server.EXPOSED))
            self.assertFalse(any(n.startswith("robot") for n in registered))   # 로봇 도구는 열지 않음
            self.assertEqual(len(registered["vision_topview"]()), 2)
            self.assertFalse(registered["notify"]("alert", "010-1111-2222")["ok"])
        finally:
            for k in ("mcp", "mcp.server", "mcp.server.fastmcp"):
                sys.modules.pop(k, None)



class AnswerKeyTest(unittest.TestCase):
    def setUp(self):
        from evaluation import answer_key
        self.ak = answer_key
        self.truths = answer_key.to_truths(answer_key.load(ROOT / "evaluation" / "answer_key_template.csv"))

    def test_template_is_valid(self):
        errs, warns = self.ak.check(self.truths)
        self.assertEqual(errs, [])
        self.assertEqual(warns, [])

    def test_session_leak_detected(self):
        t = [dict(x) for x in self.truths]
        t[3] = dict(t[3], photo_id="wallet_W01_s3_009.jpg", session="s3")   # 검증용 사진을 개선용 세션으로
        errs, _ = self.ak.check(t)
        self.assertTrue(any("데이터 누수" in e for e in errs))

    def test_bad_values(self):
        import copy
        t = copy.deepcopy(self.truths)
        t[0]["fields"]["color"] = {"value": "보라", "visibility": "보임"}
        t[1]["fields"]["shape"] = {"value": "", "visibility": "보임"}
        t[2]["fields"]["mark"]["visibility"] = "보여요"
        t[4]["category"] = "USB"
        errs, _ = self.ak.check(t)
        joined = " ".join(errs)
        for word in ("색 목록", "정답 값이 비었음", "중 하나여야", "파일 이름 품목"):
            self.assertIn(word, joined)

    def test_incomplete_val_split(self):
        import copy
        t = copy.deepcopy(self.truths)
        for x in t:
            if x["split"] == "검증용":
                for f in x["fields"].values():
                    f["visibility"] = "보임"
                    f["value"] = f["value"] or "가죽"
        errs, _ = self.ak.check(t)
        self.assertTrue(any("검증용" in e and "안 보임" in e for e in errs))


class EvalVisionTest(unittest.TestCase):
    def test_perfect_and_final_guard(self):
        import tempfile
        from evaluation import answer_key, eval_vision
        key = ROOT / "evaluation" / "answer_key_template.csv"
        truths = answer_key.to_truths(answer_key.load(key))
        preds = {}
        for t in truths:   # 정답과 똑같이 답하고, 안 보이는 항목은 보류
            preds[t["photo_id"]] = {"category": t["category"], **{f: (s["value"] if s["visibility"] == "보임" else "확인 불가")
                                                                for f, s in t["fields"].items()}}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "preds.json"
            p.write_text(json.dumps(preds, ensure_ascii=False), encoding="utf-8")
            r = eval_vision.run(key, p, "개선용")
            self.assertEqual(r["score"], 100.0)
            self.assertEqual(r["mistakes"], [])
            with self.assertRaises(SystemExit):
                eval_vision.run(key, p, "최종")
            self.assertEqual(eval_vision.run(key, p, "최종", final=True)["photos"], 2)
            first = truths[0]["photo_id"]
            preds[first]["material"] = "가죽"   # 안 보이는데 단정
            p.write_text(json.dumps(preds, ensure_ascii=False), encoding="utf-8")
            r2 = eval_vision.run(key, p, "개선용")
            self.assertTrue(any("지어냄" in m for m in r2["mistakes"]))
            self.assertLess(r2["P"], 1.0)


class ReviewerTest(unittest.TestCase):
    def fake(self, content=None, exc=None):
        from unittest import mock
        import io

        class Res(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=0):
            if exc:
                raise exc
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["format"], "json")
            return Res(json.dumps({"message": {"content": content}}).encode("utf-8"))
        return mock.patch("urllib.request.urlopen", urlopen)

    def test_ok_and_hold(self):
        from agents.llm_reviewer import OllamaReviewer
        with self.fake('{"verdict": "ok", "note": "이상 없음"}'):
            self.assertEqual(OllamaReviewer()({"case": "x"}), ("ok", "이상 없음"))
        with self.fake('{"verdict": "hold", "note": "상태가 이상함"}'):
            self.assertEqual(OllamaReviewer()({"case": "x"})[0], "hold")

    def test_errors_become_hold(self):
        import urllib.error
        from agents.llm_reviewer import OllamaReviewer
        with self.fake(exc=urllib.error.URLError("꺼짐")):
            self.assertEqual(OllamaReviewer()({})[0], "hold")
        with self.fake("승인합니다"):   # JSON 아님
            self.assertEqual(OllamaReviewer()({})[0], "hold")
        with self.fake('{"verdict": "approve"}'):   # 정해진 값 아님
            self.assertEqual(OllamaReviewer()({})[0], "hold")

    def test_reviewer_in_flow(self):
        from agents.llm_reviewer import OllamaReviewer
        be = backend()
        with self.fake('{"verdict": "hold", "note": "기록 확인 필요"}'):
            out = run_return(ReturnRequest("T", "A-1"), be, Reporter(), reviewer=OllamaReviewer())
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertFalse(be.robot_moved())


if __name__ == "__main__":
    unittest.main()
