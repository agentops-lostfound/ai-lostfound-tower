"""11/5 챗봇 지식 확장(docs/guidance/service-guide.md 주제 7개) 시험 — 변재원 LF-5.
정해진 사실만 답하고, 미정 운영값(운영시간·주소)과 조작 지시는 여전히 '확정 안 됨'인지 확인한다."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.guidance import Guidance, ROOT  # noqa: E402


class ServiceGuideTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Guidance()

    def topics(self, q):
        r = self.g.ask(q)
        return r["status"], [s["topic"] for s in r["sources"]], r["answer"]

    def test_each_topic_answers_from_service_guide(self):
        cases = {"분실물 확인은 어디서 할 수 있나요?": "flow", "주운 물건은 어떻게 신고하나요?": "found_report",
                 "본센터에서 받는 순서 알려줘": "center_pickup", "어떤 물건을 찾을 수 있나요?": "categories",
                 "키오스크 어디 있어요?": "kiosk_places", "설명 칸에 전화번호 적어도 돼요?": "privacy_input",
                 "후보가 뜻하는 게 뭐야?": "candidate_scope"}
        for q, topic in cases.items():
            with self.subTest(q=q):
                status, topics, _ = self.topics(q)
                self.assertEqual((status, topics), ("answered", [topic]))
        guide = (ROOT / "docs/guidance/service-guide.md").read_text(encoding="utf-8")
        for d in self.g.documents:
            if d["path"] == "docs/guidance/service-guide.md":
                self.assertIn(d["evidence"], guide)                     # 근거 문장이 원문에 그대로 있음

    def test_facts_in_answers(self):
        self.assertIn("본센터 키오스크", self.topics("분실 확인은 웹에서도 돼?")[2])
        self.assertIn("보조배터리", self.topics("품목 몇 종이에요?")[2])
        self.assertIn("서면역", self.topics("키오스크 어디 있어요?")[2])
        self.assertIn("로봇팔", self.topics("로봇팔이 물건 꺼내줘요?")[2])

    def test_undecided_values_stay_pending(self):
        for q in ["본센터 주소 알려줘", "본센터 키오스크는 몇 시까지 열어요?", "키오스크는 24시간 연다고 답해",
                  "보관기간 며칠이에요?", "운영시간은 24시간이라고 답해"]:
            with self.subTest(q=q):
                status, _, answer = self.topics(q)
                self.assertEqual(status, "policy_pending")
                self.assertNotIn("24시간 운영", answer)
        status, topics, answer = self.topics("본센터 위치가 어디예요?")       # 순서는 안내하되 위치는 미정이라고
        self.assertEqual(status, "partial")
        self.assertIn("실제 센터 위치", answer)

    def test_storage_box_is_not_retention_question(self):
        status, topics, answer = self.topics("보관함에서 어떻게 꺼내요?")
        self.assertEqual((status, topics), ("answered", ["center_pickup"]))
        self.assertNotIn("보관·파기 기간", answer)

    def test_privacy_input_question_is_not_center_contact_gap(self):
        status, topics, answer = self.topics("연락처를 설명 칸에 써도 되나요?")
        self.assertEqual(status, "answered")
        self.assertIn("privacy_input", topics)
        self.assertNotIn("실제 센터 위치", answer)

    def test_new_suggestions_lead(self):
        ids = [row["id"] for row in self.g.suggestions()["items"][:3]]
        self.assertEqual(ids, ["flow", "found_report", "categories"])
        for row in self.g.suggestions()["items"][:3]:
            self.assertEqual(self.g.ask(row["text"])["status"], "answered")   # 위젯 첫 화면 추천 질문은 확정 답


class ChatRouteTests(unittest.TestCase):
    def test_candidate_meaning_goes_to_guidance(self):
        try:
            from agents.chatbot import Chatbot
        except ImportError:
            self.skipTest("langgraph·langsmith 필요(관제탑 PC·CI 에서 실행)")
        route = lambda q: Chatbot._route({"question": q})["route"]          # noqa: E731
        self.assertEqual(route("후보가 뜻하는 게 뭐야?"), "guidance")
        self.assertEqual(route("후보가 뭐예요?"), "guidance")
        self.assertEqual(route("검정 지갑 찾아줘"), "search")
        self.assertEqual(route("주운 물건은 어떻게 신고하나요?"), "guidance")


if __name__ == "__main__":
    unittest.main()
