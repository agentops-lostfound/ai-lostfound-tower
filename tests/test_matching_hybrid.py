import unittest
from unittest.mock import Mock
from matching.hybrid import HybridMatcher, free_feature_text
from matching.policy import load_config


class HybridTests(unittest.TestCase):
    def candidate(self, ident, color, category="card_wallet", **extra):
        return {"id": ident, "features": {"category": category, "colors": [color], **extra}}

    def test_filter_before_embedding(self):
        ranker = Mock()
        ranker.prepare.return_value = {}
        ranker.rank.return_value = ([{"id": 1, "cosine_similarity": .8}], {})
        matcher = HybridMatcher(load_config(), ranker=ranker)
        candidates = [self.candidate(0, "yellow"), self.candidate(1, "blue", distinctive_features=["corner scratch"])]
        ranking, decision, _ = matcher.match(candidates, {"colors": ["blue"], "free_text": "a scratch near the corner"})
        self.assertEqual([c["id"] for c in ranker.prepare.call_args.args[0]], [1])
        self.assertEqual(decision["selected_id"], 1)

    def test_attributes_only_skip_model_and_related_category_survives(self):
        ranker = Mock()
        matcher = HybridMatcher(load_config(), ranker=ranker)
        _, decision, _ = matcher.match([self.candidate(0, "dark blue", category="wallet")],
                                     {"category": "card_wallet", "colors": ["navy"]})
        ranker.prepare.assert_not_called()
        self.assertEqual(decision["status"], "matched")

    def test_ambiguous_and_unknown_stay_unconfirmed(self):
        matcher = HybridMatcher(load_config())
        for candidates in ([self.candidate(0, "blue"), self.candidate(1, "blue")],
                           [self.candidate(0, "unknown")]):
            _, decision, _ = matcher.match(candidates, {"colors": ["blue"]})
            self.assertEqual(decision["status"], "needs_confirmation")

    def test_free_query_missing_observations_requires_confirmation(self):
        matcher = HybridMatcher(load_config())
        _, decision, _ = matcher.match([self.candidate(0, "blue")], {"colors": ["blue"], "free_text": "star sticker"})
        self.assertIn("missing_free_features", decision["reasons"])

    def test_free_features_do_not_repeat_color_category_absence(self):
        text = free_feature_text({"category": "phone", "colors": ["blue"],
                                  "sticker_status": "absent", "distinctive_features": ["corner scratch"]})
        self.assertEqual(text, "distinctive features: corner scratch")

    def test_invalid_query_rejected_before_model_load(self):
        matcher = HybridMatcher(load_config())
        with self.assertRaises(ValueError):
            matcher.match([], {"free_text": "\ud30c\ub780"})
