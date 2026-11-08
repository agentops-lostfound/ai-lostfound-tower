"""11/9 분실물 서비스 밖 질문(날씨·맛집 등) — 지명 낱말 때문에 엉뚱한 안내가 걸리던 것
실측(사용자 화면): "오늘 해운대 날씨 어때" → 역 키오스크 위치, "어제 부산역 날씨 어땠어?" → 본센터 도착 시간"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_rag import GAP_LEAD, MENU, GroundedRag, answer_gap  # noqa: E402
from agents.guidance import OFF_TOPIC_ANSWER, Guidance, off_topic  # noqa: E402

OFF = ["오늘 해운대 날씨 어때", "어제 부산역 날씨 어땠어?", "내일 서면 미세먼지 어때요?", "부산역 근처 맛집 추천해줘",
       "맛집 찾아줘", "해운대 가는 버스 몇분 남았어?", "오늘 주식 어때", "어제 야구 몇대몇이야?", "오늘 뉴스 알려줘"]
# 서비스 질문 — 날씨·지명 낱말이 섞여도 막으면 안 됨
SERVICE = ["해운대역 키오스크 어디 있어요?", "비 오는 날 우산 잃어버렸어요", "날씨 때문에 늦게 가도 돼요?",
           "부산역 본센터 운영시간 알려줘", "서면역에서 지갑 주웠어요"]
KIOSK_EV = "역 키오스크는 해운대역(KIOSK-A)과 서면역(KIOSK-C)에 있어요"


def no_model(_payload):
    raise AssertionError("서비스 밖 질문은 모델을 부르지 않아야 함")


class OffTopicRuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guide = Guidance()

    def test_off_topic_gets_fixed_sentence_without_model(self):
        rag = GroundedRag(self.guide, "m", request=no_model)
        for q in OFF:
            with self.subTest(q=q):
                self.assertTrue(off_topic(q))
                r = rag.ask(q)
                self.assertEqual(r["answer"], OFF_TOPIC_ANSWER)
                self.assertTrue(r["answer"].startswith("분실물 찾기·습득 신고·물건 받는 방법만 안내할 수 있어요."))
                self.assertEqual((r["status"], r["generation_status"], r["sources"]), ("not_found", "off_topic", []))
                self.assertEqual(r["choices"], MENU)
                self.assertNotIn("키오스크는 해운대역", r["answer"])
                self.assertFalse(r["generation_used"])

    def test_service_questions_are_not_blocked(self):
        rag = GroundedRag(self.guide, None)
        for q in SERVICE:
            with self.subTest(q=q):
                self.assertFalse(off_topic(q))
                r = rag.ask(q)
                self.assertNotEqual(r["answer"], OFF_TOPIC_ANSWER)
                self.assertNotEqual(r.get("generation_status"), "off_topic")
        r = rag.ask("해운대역 키오스크 어디 있어요?")
        self.assertEqual([s["topic"] for s in r["sources"]], ["kiosk_places"])
        r = rag.ask("날씨 때문에 늦게 가도 돼요?")          # 늦게 가도 되는지 = 보관 기간
        self.assertEqual([s["topic"] for s in r["sources"]], ["retention"])
        self.assertIn("14일", r["answer"])
        r = rag.ask("비 오는 날 우산 잃어버렸어요")         # 잃어버림 → 어떤 물건인지 되묻기(찾을 수 있는 6종 안내)
        self.assertEqual(r["status"], "clarification_needed")

    def test_chatbot_does_not_send_off_topic_to_item_search(self):
        from agents.chatbot import Chatbot
        bot = Chatbot(self.guide)
        r = bot.ask("맛집 찾아줘")
        self.assertEqual(r["agent"], "guidance")
        self.assertFalse(r["item_search_performed"])
        self.assertEqual(r["answer"], OFF_TOPIC_ANSWER)


class OffTopicAnswerGapTest(unittest.TestCase):
    """모델이 있을 때: 날씨 질문에 지명만 같은 안내로 답하면 '자료에 없음'(uncovered)"""

    def test_weather_answer_is_uncovered(self):
        self.assertEqual(answer_gap("오늘 해운대 날씨 어때", KIOSK_EV + "."), "uncovered")
        self.assertEqual(answer_gap("어제 부산역 날씨 어땠어?", "맡긴 물건은 1시간마다 본센터로 옮겨져요."), "uncovered")
        self.assertIsNone(answer_gap("해운대역 키오스크 어디 있어요?", KIOSK_EV + "."))

    def test_fake_model_weather_answer_becomes_honest(self):
        """규칙을 지나 모델까지 간 경우(가짜 모델): 첫 답 → 다시 쓰기 → 모델도 '자료에 없음' → 자료에 없다고 솔직히"""
        log = []
        replies = [{"mode": "answer", "passage_ids": [0], "sentences": [{"evidence": KIOSK_EV, "sentence": KIOSK_EV + "."}]},
                   {"mode": "answer", "passage_ids": [0], "answerable": False,
                    "sentences": [{"evidence": KIOSK_EV, "sentence": KIOSK_EV + "."}]}]

        def request(payload):
            log.append(json.loads(payload["messages"][1]["content"]))
            return {"message": {"content": json.dumps(replies.pop(0))}}
        rag = GroundedRag(Guidance(), "m", request=request)
        out = rag._generate("오늘 해운대 날씨 어때", [{"id": 0, "topic": "kiosk_places", "text": KIOSK_EV + "."}], allow_clarify=False)
        self.assertTrue(out["answer"].startswith(GAP_LEAD), out)
        self.assertIn("not_addressed:uncovered", out["note"])
        self.assertEqual(len(log), 2)
        self.assertIn("서비스 밖", log[1]["feedback"]["problem"])


if __name__ == "__main__":
    unittest.main()
