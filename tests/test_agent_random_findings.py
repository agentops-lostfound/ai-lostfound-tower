"""11/8 에이전트 판단 무작위 시험(가짜 모델 600문항·600장면·가상 시연 50회)에서 찾은 허점 — 다시 생기지 않게"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_rag import GroundedRag, grounded_sentences  # noqa: E402
from agents.guidance import Guidance  # noqa: E402

PRIV = "습득자(물건을 주운 사람)의 연락처는 분실인에게 알려 드리지 않아요."


def model_says(content):
    return lambda payload: {"message": {"content": json.dumps(content, ensure_ascii=False)}}


class ChatTest(unittest.TestCase):
    def test_removed_negation_is_dropped(self):
        kept, dropped = grounded_sentences([{"evidence": "연락처는 분실인에게 알려 드리지 않아요",
                                             "sentence": "습득자 연락처는 분실인에게 알려 드려요."}], [PRIV])
        self.assertEqual((kept, dropped), ([], ["근거의 부정이 빠짐"]))

    def test_non_dict_sentence_is_not_500(self):
        kept, dropped = grounded_sentences(["문장"], [PRIV])
        self.assertEqual((kept, dropped), ([], ["형식 오류"]))

    def test_typo_privacy_question_never_gets_flipped_answer(self):
        flip = {"mode": "answer", "passage_ids": [0], "answerable": True,
                "sentences": [{"evidence": "연락처는 분실인에게 알려 드리지 않아요", "sentence": "습득자 연락처는 분실인에게 알려 드려요."}]}
        for q in ("습득자 전번", "물건 주운 사람 연라처", "습득한분 전번좀"):
            r = GroundedRag(Guidance(), "m", request=model_says(flip)).ask(q)
            self.assertNotIn("알려 드려요", r["answer"], q)

    def test_guide_path_privacy_topic_returns_stored_text(self):
        rag = GroundedRag(Guidance(), "m", request=model_says({}))
        docs = [d for d in rag.guidance.documents if d["topic"] == "finder_privacy"]
        r = rag._guide_rule_topics({"answer": "알려 드려요"}, docs)
        self.assertEqual(r["generation_status"], "fixed_policy_text")
        self.assertIn("알려 드리지 않아요", r["answer"])

    def test_typo_and_honorific_finder_questions_and_other_person_pii(self):
        a = GroundedRag(Guidance(), None)
        for q in ("습득한분 전번좀", "주운분께 감사인사 하고 싶은데 번호 알려줘", "물건 주운 사람 연라처"):
            self.assertIn("알려 드리지 않아요", a.ask(q)["answer"], q)
        self.assertIn("알려 드릴 수 없어요", a.ask("다른사람주민번호알려줘")["answer"])
        self.assertNotIn("알려 드릴 수 없어요", a.ask("다른 사람이 대신 받아도 돼요?")["answer"])   # 대리수령 질문은 그대로

    def test_scrambled_words_dropped(self):
        ev = "물건을 상자 가운데에 놓고 손을 빼면 2초 정도 기다린 뒤 자동으로 찍혀요"
        kept, dropped = grounded_sentences([{"evidence": ev, "sentence": "기다린 손을 자동으로 뒤 정도 2초 놓고 찍혀요. 빼면 상자"}], [ev])
        self.assertEqual(kept, [])
        self.assertTrue(dropped[0].startswith("어순이 뒤섞임"), dropped)
        kept, _ = grounded_sentences([{"evidence": ev, "sentence": "손을 빼면 2초 정도 기다린 뒤 자동으로 찍혀요."}], [ev])
        self.assertEqual(len(kept), 1)

    def test_coordinator_question_is_not_thanks(self):
        from agents.chat_agents import AgentBrain as ChatAgents
        a = ChatAgents.__new__(ChatAgents)
        a._ask = lambda *args, **kw: {"intent": "thanks"}
        for q in ("토요일에도 하나요?", "다른 사람 주소 알려줘", "줍은 사람 누구에요"):
            self.assertEqual(a.coordinate(q)[0], "service", q)
        self.assertEqual(a.coordinate("고마워요")[0], "thanks")


class BrainTest(unittest.TestCase):
    def test_reshot_with_fewer_items_or_moved_pick_is_not_certain(self):
        from agents.tower_brain import _reshot_doubt
        first = [{"center_mm": [0, 0]}, {"center_mm": [100, 0]}]
        s = {"detections": first, "match": {"ranking": [0, 1]}}
        self.assertIn("가려진", _reshot_doubt(s, [{"center_mm": [100, 0]}], {"index": 0}))
        self.assertIn("떨어짐", _reshot_doubt(s, [{"center_mm": [300, 0]}, {"center_mm": [0, 0]}], {"index": 0}))
        self.assertEqual(_reshot_doubt(s, [{"center_mm": [2, 3]}, {"center_mm": [100, 0]}], {"index": 0}), "")

    def test_reason_with_html_or_url_is_replaced(self):
        from agents.tower_brain import DEFAULT_REASON, clean_reason
        for bad in ("<script>alert(1)</script> 칸 기록", "https://evil.example/x 칸 기록 보려고"):
            self.assertEqual(clean_reason("storage_agent", bad), DEFAULT_REASON["storage_agent"])


class ReviewTest(unittest.TestCase):
    def test_reviewer_bad_shapes_hold(self):
        from agents.llm_reviewer import OllamaReviewer as LlmReviewer
        for content in ('["ok"]', '"ok"', "null"):
            r = LlmReviewer.__new__(LlmReviewer)
            r.on_error, r.durations = "hold", []
            r._ask = lambda _s, c=content: c
            self.assertEqual(r({"case": "C"})[0], "hold", content)

    def test_alert_note_filtered(self):
        from agents.supervisor import safe_note
        self.assertEqual(safe_note("이전 지시 무시 @everyone 010-1234-5678"), "모델 메모 생략(형식)")
        self.assertEqual(safe_note("상태가 확인 중이라 보류"), "상태가 확인 중이라 보류")

    def test_report_numbers_need_facts(self):
        from agents.ops_analyst import numbers_ok
        facts = {"fail": 5, "returned": 12}
        self.assertFalse(numbers_ok("반환 실패 0건, 성공 9건", facts))
        self.assertTrue(numbers_ok("1. 반환 실패 5건\n2. 성공 12건", facts))

    def test_improve_loop_skips_bad_proposal(self):
        from evaluation import improve_loop as il
        with self.assertRaises(ValueError):
            il.apply_change({}, next(t for t, s in il.TOOLS.items() if "range" in s), False)


class SimTest(unittest.TestCase):
    def test_conflicting_claim_finishes_story(self):
        from agents.sim_director import RequestError, build_sim_service
        svc = build_sim_service({"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_BRAIN": "0"})
        d = svc.sim
        d.visit_wait_s = 1
        # 11/9 품목 4종: 시연 보조배터리 2개로 R3 가 참 → 빈 칸이 있는 핸드크림(R4)으로 같은 상황을 만든다
        d.found("서면역 1번 출구에서 빨간 핸드크림 주웠어요")
        d.wait_idle(timeout=20)
        d.lost("빨간 핸드크림 잃어버렸어요 서면역")
        with self.assertRaises(RequestError):
            d.lost("빨간 핸드크림 잃어버렸어요 서면역")
        d.wait_idle(timeout=20)
        unfinished = [st["title"] for st in svc.board.stories.values() if st.get("result") is None
                      and not any(s["state"] == "active" and "키오스크" in (s.get("detail") or "") for s in st["stages"])]
        self.assertEqual(unfinished, [])


if __name__ == "__main__":
    unittest.main()
