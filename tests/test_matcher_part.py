"""매칭 부품 연결(agents/matcher_part.py): 김건태 matching/policy.py → 관제탑 match_item 약속."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.backends import check_part  # noqa: E402
from agents.contracts import MATCH_NONE, MATCH_OK, MATCH_UNCERTAIN, NONE, UNKNOWN  # noqa: E402
from agents.matcher_part import (PolicyMatcherPart, free_text, matcher_part_from_env,  # noqa: E402
                                 to_policy_features, word_overlap)
from tools import mock_scene as ms  # noqa: E402


def det(color, mark=NONE, text=UNKNOWN, cat="지갑"):
    return {"box": [0, 0, 10, 10], "center": [5, 5],
            "features": {"category": cat, "color": color, "shape": "rectangular", "material": "plastic",
                         "mark": mark, "visible_text": text, "confidence": 0.9}}


class ConvertTest(unittest.TestCase):
    def test_contract_to_policy(self):
        self.assertEqual(to_policy_features({"category": "지갑", "color": "빨강", "mark": NONE}),
                         {"category": "card_wallet", "colors": ["red"], "sticker_status": "absent"})
        self.assertEqual(to_policy_features({"category": "보조배터리", "color": "기타", "mark": "star sticker"}),
                         {"category": "power_bank", "colors": [], "sticker_status": "present"})   # '기타'는 조건 아님
        self.assertEqual(to_policy_features({}), {"category": "unknown", "colors": [], "sticker_status": "unknown"})

    def test_free_text_and_overlap(self):
        self.assertEqual(free_text({"mark": "star sticker (front)", "visible_text": NONE}), "star sticker (front)")
        self.assertEqual(word_overlap("star sticker", "star sticker"), 1.0)
        self.assertEqual(word_overlap("", "x"), 0.0)


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.m = PolicyMatcherPart()

    def test_part_shape(self):
        self.assertEqual(check_part(self.m, "matcher"), [])

    def test_clear_match_and_color_reject(self):
        q = {"category": "지갑", "color": "빨강", "mark": NONE, "visible_text": UNKNOWN}
        r = self.m.match_item(q, [det("검정"), det("빨강"), det("흰색")])
        self.assertEqual((r["status"], r["index"]), (MATCH_OK, 1))
        r = self.m.match_item(q, [det("검정"), det("흰색")])
        self.assertEqual(r["status"], MATCH_NONE)                  # 색이 확실히 다르면 후보 없음

    def test_unknown_color_is_not_auto(self):
        q = {"category": "지갑", "color": "빨강", "mark": NONE}
        r = self.m.match_item(q, [det(UNKNOWN), det("검정")])
        self.assertEqual(r["status"], MATCH_UNCERTAIN)            # 모르면 확정하지 않음

    def test_policy_error_is_none(self):
        bad = PolicyMatcherPart(config={"broken": True})
        r = bad.match_item({"color": "빨강"}, [det("빨강")])
        self.assertEqual(r["status"], MATCH_NONE)
        self.assertIn("error", bad.last_decision)

    def test_env_switch(self):
        self.assertIsNone(matcher_part_from_env({}))
        self.assertIsInstance(matcher_part_from_env({"TOWER_MATCHER": "Policy"}), PolicyMatcherPart)
        from agents.mcp_server import default_backend
        self.assertEqual(default_backend({"TOWER_MATCHER": "policy"}).sources()["match_item"], "PolicyMatcherPart")


class SceneWithPolicyTest(unittest.TestCase):
    def test_never_wrong_object(self):
        results = {r["case_id"]: r for r in ms.run_all(matcher=ms.make_matcher("policy"))}
        self.assertFalse(any(r["decision"] == "wrong_object" for r in results.values()))
        self.assertEqual(results["S03"]["decision"], "returned")   # dark red → 빨강 으로 맞춰 넘겨 색 불일치 안 남
        for cid in ("S05", "S06", "S08", "S09"):
            self.assertEqual(results[cid]["decision"], "staff_check", cid)


if __name__ == "__main__":
    unittest.main()
