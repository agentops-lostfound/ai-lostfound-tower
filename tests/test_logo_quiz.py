"""11/11 실물 시험: 아이폰 목업 뒤 사과 로고 — 분실인이 '사과'라고 답했는데 Qwen 은 영어로 적어 확인 질문이 '글자 틀림'이 됐다"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import logo_tokens  # noqa: E402
from agents.sim_director import _same_text  # noqa: E402
from agents.sim_world import query_features  # noqa: E402
from agents.vision_adapter import to_features  # noqa: E402


class LogoQuizTest(unittest.TestCase):
    def test_korean_and_english_logo_words_match(self):
        for said, stored in [("사과", "apple logo"), ("사과 로고", "Apple"), ("애플이요", "apple-shaped logo"),
                             ("삼성", "SAMSUNG"), ("별 스티커", "star sticker (back)"), ("VOVA", "vova")]:
            self.assertTrue(_same_text(said, stored), (said, stored))

    def test_wrong_or_empty_answer_still_fails(self):
        for said, stored in [("삼성", "apple logo"), ("", "apple"), ("로고", "apple logo"), ("아이폰", "apple logo"), ("글자", "VOVA")]:
            self.assertFalse(_same_text(said, stored), (said, stored))

    def test_logo_word_alone_is_not_evidence(self):
        self.assertEqual(logo_tokens("logo 로고 스티커"), set())

    def test_qwen_logo_in_features_goes_to_visible_text(self):
        q = {"category": "phone", "colors": ["white"], "logos_or_text": [], "distinctive_features": ["apple logo on the back"]}
        self.assertEqual(to_features(q, 0.8)["visible_text"], "apple logo")
        q["distinctive_features"] = ["small logo", "camera bump"]                 # 무슨 로고인지 모르면 지어내지 않음
        self.assertEqual(to_features(q, 0.8)["visible_text"], "확인 불가")

    def test_claimant_words(self):
        self.assertEqual(query_features("흰색 휴대폰 뒤에 사과 로고 잃어버렸어요")["visible_text"], "사과")
        self.assertNotIn("visible_text", query_features("흰색 아이폰 잃어버렸어요"))


if __name__ == "__main__":
    unittest.main()
