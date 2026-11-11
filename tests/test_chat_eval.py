"""11/9 질문 500개 채점표(evaluation/chat_eval.py) 시험 — 채점 규칙·단계 이름·엑셀 누적·문항 파일 형식"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evaluation import chat_eval as ce  # noqa: E402

ITEMS = json.loads(ce.QUESTIONS.read_text(encoding="utf-8"))


class QuestionFileTest(unittest.TestCase):
    def test_500_items_well_formed(self):
        self.assertEqual(len(ITEMS), 500)
        self.assertEqual([it["no"] for it in ITEMS], list(range(1, 501)))
        allowed = {"any", "all", "not", "status", "gen", "gen_not", "path_has", "path_not", "choices_any", "cand", "id", "http"}
        for it in ITEMS:
            self.assertTrue(it["turns"], it["no"])
            for t in it["turns"]:
                self.assertTrue(t.get("say") or t.get("action"), it["no"])
                self.assertLessEqual(set(t.get("expect", {})), allowed, it["no"])
            self.assertTrue(any("expect" in t for t in it["turns"]), f"{it['no']}: 확인할 것이 없음")
        self.assertEqual(sum(1 for it in ITEMS if it.get("lf")), 50)        # Langfuse 고정 50문항

    def test_levels_cover_basic_to_task(self):
        levels = {it["level"] for it in ITEMS}
        self.assertEqual(levels, {"1 기본 안내", "2 물건 검색", "3 이어 묻기·복합", "4 임무 수행", "5 안전·예외", "6 직원 관제"})
        self.assertGreaterEqual(sum(1 for it in ITEMS if len(it["turns"]) >= 5), 60)   # 챗봇이 끝까지 수행하는 여러 턴 대화

    def test_no_exact_duplicates(self):
        sig = [json.dumps([(t.get("say"), t.get("action"), t.get("staff"), t.get("mode")) for t in it["turns"]], ensure_ascii=False)
               for it in ITEMS]
        self.assertEqual(len(sig), len(set(sig)))


class CheckTurnTest(unittest.TestCase):
    def test_rules(self):
        res = {"answer": "후보 1개를 찾았어요", "choices": ["분실 접수하기"], "status": "items_found",
               "agent_path": ["coordinator", "planner", "supervisor", "item_search"], "candidates": [{}]}
        ok = {"expect": {"any": ["후보"], "path_has": ["item_search"], "choices_any": ["분실 접수하기"], "cand": [1, None]}}
        self.assertEqual(ce.check_turn(ok, 200, res), [])
        bad = {"expect": {"cand": [0, 0], "path_not": ["item_search"], "not": ["후보"], "status": ["intake_done"]}}
        why = ce.check_turn(bad, 200, res)
        self.assertEqual(len(why), 4, why)
        self.assertEqual(ce.check_turn({"expect": {"http": 422}}, 422, {}), [])
        self.assertTrue(ce.check_turn({}, 422, {}))                           # 기대하지 않은 거절은 실패

    def test_common_checks(self):
        self.assertIn("빈 답", ce.check_turn({}, 200, {"answer": ""}))
        self.assertTrue(ce.check_turn({}, 200, {"answer": "번호 900101-1234567 확인"}))   # 주민번호 원문
        self.assertTrue(ce.check_turn({}, 200, {"answer": "finder_privacy 문서"}))        # 영어 주제 이름
        self.assertEqual(ce.check_turn({}, 200, {"answer": "", "status": "intake_none"}), [])


class StepAndExcelTest(unittest.TestCase):
    def test_step_names_per_day(self):
        now = dt.datetime(2026, 11, 9, 15, 0)
        self.assertEqual(ce.next_step_name([], now), "11/9 01")
        self.assertEqual(ce.next_step_name(["11/9 01", "11/8 01"], now), "11/9 02")

    def test_excel_accumulates_steps_and_overrides(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl 필요")
        items = ITEMS[:3]
        runs = [{"meta": {"step": "11/9 01", "started": "2026-11-09 10:00:00", "seconds": 60, "commit": "a", "model": {}},
                 "results": [{"no": 1, "score": 1, "why": [], "turns": [{"answer": "a"}]},
                             {"no": 2, "score": 0, "why": ["x"], "turns": [{"answer": "b"}]},
                             {"no": 3, "score": 1, "why": [], "turns": [{"answer": "c"}]}]},
                {"meta": {"step": "11/9 02", "started": "2026-11-09 11:00:00", "seconds": 60, "commit": "b", "model": {}},
                 "results": [{"no": 1, "score": 0, "why": ["y"], "turns": [{"answer": "a"}]},
                             {"no": 2, "score": 1, "why": [], "turns": [{"answer": "b"}]},
                             {"no": 3, "score": 0, "why": ["z"], "turns": [{"answer": "c"}]}]}]
        with tempfile.TemporaryDirectory() as d:
            ov = Path(d) / "ov.csv"
            ov.write_text("단계,번호,점수,이유\n11/9 02,3,1,자동 채점 오판\n", encoding="utf-8-sig")
            out = Path(d) / "s.xlsx"
            with mock.patch.object(ce, "OVERRIDES", ov):
                ce.build_excel(items, runs, out)
            wb = openpyxl.load_workbook(out)
            ws = wb["점수"]
            self.assertEqual([c.value for c in ws[1]][-2:], ["11/9 01", "11/9 02"])
            self.assertEqual([ws.cell(row=r, column=8).value for r in (2, 3, 4)], [0, 1, 1])   # 3번은 사람 판정 1
            self.assertEqual(ws.cell(row=5, column=8).value, "=SUM(H2:H4)")
            self.assertEqual(ws.cell(row=2, column=8).fill.fgColor.rgb[-6:], "FF453A")        # 1→0 빨강
            self.assertEqual(ws.cell(row=3, column=8).fill.fgColor.rgb[-6:], "34C759")        # 0→1 초록
            info = wb["단계 정보"]
            self.assertEqual((info.cell(row=3, column=7).value, info.cell(row=3, column=8).value), (1, 1))  # 0→1 2번 · 1→0 1번(3번은 사람 판정으로 1 유지)
            self.assertEqual(wb["사람 판정"].cell(row=2, column=4).value, "자동 채점 오판")


class RunnerTest(unittest.TestCase):
    def test_runs_a_task_scenario_in_fresh_sim(self):
        env = {"LF_LANGFUSE": "0", **ce.SIM_ENV}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("LF_CHAT_RAG_MODEL", None)
            r = ce.Runner()
            item = {"no": 9999, "turns": [{"say": "주운 물건 신고하고 싶어요"}, {"say": "초량 5번 출구 앞에서 검정 립밤"},
                                          {"say": "접수할게요", "expect": {"status": ["intake_done"], "id": r"[A-Z]-\d{8}-\d{4}"}}]}
            x = r.run_item(item)
            self.assertEqual(x["score"], 1, x["why"])
            again = r.run_item(item)                       # 새 가상 관제탑이라 같은 번호부터 다시
            self.assertEqual(again["turns"][-1]["answer"][:40], x["turns"][-1]["answer"][:40])


if __name__ == "__main__":
    unittest.main()
