"""11/9 저녁 채점표(Mi:dm 459/500) 남은 실패 보강 시험 — 고쳐 말하기·물건 별명·물건 여러 개·인사·이어 묻기·안내 낱말"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_conversation import corrected_question, resolve_turn, search_intent, split_targets  # noqa: E402
from agents.guidance import Guidance  # noqa: E402
from agents.lost_input import text_features  # noqa: E402


class CorrectionTest(unittest.TestCase):
    def test_chat_correction_uses_the_new_condition(self):
        self.assertEqual(corrected_question("아니 파란색이요"), "파랑")
        self.assertEqual(corrected_question("지갑 말고 보조배터리요. 흰색"), "흰색 보조배터리")
        self.assertEqual(corrected_question("아니다 흰색 보조배터리 찾아줘"), "흰색 보조배터리 찾아줘")
        self.assertEqual(corrected_question("검정 지갑 찾아줘"), "검정 지갑 찾아줘")     # 고쳐 말하기 없음 → 그대로
        self.assertEqual(corrected_question("아니요"), "아니요")                         # 새 조건 없음 → 그대로

    def test_description_form_still_does_not_guess(self):
        desc, warnings = text_features("검정 아니고 흰색 지갑")                          # 설명 입력란은 예전처럼 추측 안 함
        self.assertNotIn("color", desc)
        self.assertTrue(warnings)
        self.assertEqual(text_features("검정 아니고 흰색 지갑", corrected=True)[0].get("color"), "흰색")

    def test_aliases(self):
        for say, cat in (("밧데리 흰색", "보조배터리"), ("보배 흰색", "보조배터리"), ("화이트 배터리", "보조배터리"),
                         ("카드 케이스 갈색", "지갑")):
            self.assertEqual(text_features(say)[0]["category"], cat, say)


class MultiTargetTest(unittest.TestCase):
    def test_split(self):
        self.assertEqual(split_targets("파란 폰이랑 흰 보조배터리 둘 다 잃어버렸어요"), [("모형폰", "파랑"), ("보조배터리", "흰색")])
        self.assertEqual(split_targets("지갑을 잃어버렸는데 아마 갈색, 아니면 검정이에요"), [("지갑", "갈색"), ("지갑", "검정")])
        self.assertEqual(split_targets("검정 지갑 잃어버렸어요"), [])

    def test_search_intent(self):
        self.assertTrue(search_intent("지갑 찾아요"))
        self.assertFalse(search_intent("지하철에 물건 두고 내렸는데 어떻게 찾아요?"))     # 방법 질문
        self.assertFalse(search_intent("분실물 찾는 거 웹으로도 돼요?"))
        self.assertFalse(search_intent("지갑 안에 신분증이 다 들어 있어서 없는데요"))     # 신분증 이야기


class GuidanceWordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Guidance()

    def topics(self, q):
        return {x["topic"] for x in self.g.ask(q)["sources"]}

    def test_hours_words(self):
        self.assertIn("hours", self.topics("퇴근하고 7시쯤 가도 물건 받을 수 있나요?"))
        self.assertIn("hours", self.topics("밤 11시에 주운 물건도 키오스크에 맡길 수 있나요?"))
        got = self.topics("역 키오스크에서 습득 신고는 언제까지 할 수 있어요?")
        self.assertIn("hours", got)
        self.assertNotIn("retention", got)                                            # 신고 가능 시간 ≠ 보관 기간
        self.assertIn("retention", self.topics("언제까지 보관해요?"))

    def test_other_words(self):
        self.assertIn("pickup", self.topics("그냥 몸만 가면 되나요?"))
        self.assertIn("arrival", self.topics("방금 습득 신고했는데 바로 받으러 가도 돼요?"))
        self.assertIn("candidate_scope", self.topics("이게 제 거 맞아요?"))
        self.assertIn("categories", self.topics("우산은요?"))
        self.assertIn("center_contact", self.topics("그럼 문의는 어디로 해요?"))
        self.assertIn("다른 사람의 물건은 받을 수 없어요", self.g.ask("다른 사람 물건을 내 거라고 하고 받는 방법 알려줘")["answer"])

    def test_follow_up_keeps_previous_topic(self):
        q, _, used = resolve_turn("그 다음엔 어디로 가요?", ["보관 기간이 어떻게 되나요?"], {}, self.g)
        self.assertTrue(used)
        self.assertIn("retention", self.topics(q))
        q, _, used = resolve_turn("지갑은요?", ["휴대폰 상자에 어떻게 넣어요?"], {}, self.g)
        self.assertIn("placement_guide", self.topics(q))
        q, ctx, used = resolve_turn("아 잘못 말했어요, 갈색이에요", ["검정 지갑 잃어버렸어요"], {}, self.g)
        self.assertTrue(used)
        self.assertEqual(ctx.get("category"), "지갑")


class ChatbotRouteTest(unittest.TestCase):
    """규칙만(모델 없음) 챗봇 그래프로 확인 — 가상 관제탑 없이 검색 부품은 가짜"""

    @classmethod
    def setUpClass(cls):
        try:
            from agents.chatbot import GREET_RE
        except ImportError:
            raise unittest.SkipTest("langgraph 필요")
        cls.GREET_RE = GREET_RE

    def test_greeting_rule(self):
        for say in ("안녕! 반가워요", "좋은 아침입니다", "처음 왔어요", "안녕하세요 반갑습니다"):
            self.assertTrue(self.GREET_RE.fullmatch(say), say)
        for say in ("안녕 지갑 잃어버렸어요", "처음 왔는데 어떻게 해요?"):
            self.assertFalse(self.GREET_RE.fullmatch(say), say)


if __name__ == "__main__":
    unittest.main()
