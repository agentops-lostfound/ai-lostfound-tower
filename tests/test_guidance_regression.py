import unittest
from evaluation.evaluate_guidance import evaluate
from agents.guidance import Guidance


class GuidanceRegression(unittest.TestCase):
    def test_authored_question_set(self):
        result = evaluate()
        failed = [r["question"] for r in result["cases"] if not r["passed"]]
        self.assertEqual(failed, [])

    def test_spacing_and_unicode_do_not_change_known_intent(self):
        g = Guidance()
        for q in ["운 영 시 간 알려줘", "운영\u200b시간 알려줘", "토 요 일 문 닫나요?", "ＯＰＥＮ 시간은?"]:
            with self.subTest(question=q):
                r = g.ask(q)
                self.assertEqual((r["status"], [s["topic"] for s in r["sources"]]), ("answered", ["hours"]))

    def test_unicode_private_data_is_rejected(self):
        with self.assertRaises(ValueError):
            Guidance().ask("０１０－１２３４－５６７８ 조회해줘")
