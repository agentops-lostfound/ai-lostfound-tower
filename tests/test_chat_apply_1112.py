"""11/12 정연우 챗봇 개선본(PR #241 + zip) 적용 때 기존 500문항 채점표에서 떨어진 20문항을 고친 것의 회귀 시험.
개선본의 새 동작(결론 먼저 답·권한 우회 거절·품목 위장 거절·향 검색 한계 등)은 그대로 두고, 찾기·검색·접수 길만 되살린다."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_answer_goal import question_goal  # noqa: E402
from agents.chat_intake import detect_start  # noqa: E402
from agents.chat_turn import found_statement  # noqa: E402


class FoundStatementTest(unittest.TestCase):
    def test_how_and_search_questions_are_not_handing_in(self):
        for q in ("습득물 신고는 어떻게 해요?", "습득물 등록기계는 어느 역에 있어요?", "주운 물건은 어디에 맡기나요?",
                  "주운 물건이 두 개인데 하나씩 넣어야 해요?", "휴대폰 습득된 거 있어요?", "파란색 모형폰 습득된 거 있어요?",
                  "주운 휴대폰을 키오스크에 넣으려는데 케이스가 있는 쪽을 위로 해야 하는지 화면이 위로 가야 하는지 헷갈려요"):
            self.assertFalse(found_statement(q), q)

    def test_plain_handing_in_still_detected(self):
        for q in ("휴대폰 주웠어요", "지하철에서 립밤 주웠어요", "보조배터리를 주웠는데요"):
            self.assertTrue(found_statement(q), q)


class StartAndGoalTest(unittest.TestCase):
    def test_find_request_starts_lost_intake(self):
        self.assertEqual(detect_start("찾기 신청할게요", []), "lost")
        self.assertEqual(detect_start("찾기 요청할게요", []), "lost")
        self.assertIsNone(detect_start("찾기 신청은 어떻게 해요?", []))          # 방법을 묻는 말은 안내 길

    def test_compound_search_questions_are_not_one_goal(self):
        self.assertIsNone(question_goal("빨간색 립밤 있는지 보고 운영시간도 알려줘"))
        self.assertIsNone(question_goal("파란 휴대폰 찾고 받는 순서도 알려줘"))
        self.assertEqual(question_goal("운영시간 알려줘"), "hours")                 # 개선본 동작 유지
        self.assertEqual(question_goal("물건 찾으러 갈 때 준비물과 수령 순서를 알려줘"), "pickup_steps")
        self.assertEqual(question_goal("립밤 향기로도 찾을 수 있어요?"), "scent_search")


class ChatApiTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from agents.api import build_app
            from agents.sim_director import build_sim_service
        except ImportError:
            self.skipTest("fastapi 필요")
        svc = build_sim_service({"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_AGENT_TALK": "0", "TOWER_SIM_SEED": "full"})
        self.c = TestClient(build_app(service=svc))

    def ask(self, q, sid="apply-1112-session"):
        return self.c.post("/chat/questions", json={"question": q, "session_id": sid}).json()

    def test_found_item_question_searches(self):
        r = self.ask("휴대폰 습득된 거 있어요?")
        self.assertIn("item_search", r["agent_path"])
        self.assertGreaterEqual(len(r.get("candidates") or []), 1)

    def test_find_request_opens_intake(self):
        r = self.ask("찾기 신청할게요")
        self.assertEqual(r["status"], "intake_question")

    def test_gibberish_points_to_service(self):
        self.assertIn("분실물", self.ask("ㅁㄴㅇㄹ")["answer"])


if __name__ == "__main__":
    unittest.main()
