import copy
import tempfile
import unittest
from pathlib import Path
import yaml
from matching.policy import load_config, apply_policy, canonical


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def candidate(self, ident, color, cosine=.8, **features):
        return {"id": ident, "cosine_similarity": cosine,
                "features": {"category": "phone", "colors": color, **features}}

    def test_contradiction_beats_high_semantic_similarity(self):
        ranking, decision = apply_policy([
            self.candidate(0, ["yellow"], .99), self.candidate(1, ["blue"], .7)
        ], {"category": "phone", "colors": ["blue"]}, self.config)
        self.assertEqual(decision["selected_id"], 1)
        self.assertFalse(ranking[1]["eligible"])

    def test_single_wrong_candidate_is_no_match(self):
        _, decision = apply_policy([self.candidate(0, ["red"])], {"colors": ["blue"]}, self.config)
        self.assertEqual(decision["status"], "no_match")

    def test_unknown_does_not_reject_or_confirm(self):
        ranking, decision = apply_policy([self.candidate(0, [])], {"colors": ["blue"]}, self.config)
        self.assertTrue(ranking[0]["eligible"])
        self.assertEqual(decision["status"], "needs_confirmation")

    def test_close_colors_and_close_candidates_require_confirmation(self):
        for candidates in ([self.candidate(0, ["navy"])],
                           [self.candidate(0, ["blue"]), self.candidate(1, ["blue"], .79)]):
            _, decision = apply_policy(candidates, {"colors": ["blue"]}, self.config)
            self.assertEqual(decision["status"], "needs_confirmation")

    def test_missing_conditions_never_auto_confirm(self):
        _, decision = apply_policy([self.candidate(0, ["blue"], 1)], {}, self.config)
        self.assertEqual(decision["status"], "needs_confirmation")

    def test_absence_is_not_missing(self):
        item = self.candidate(0, ["blue"], sticker_status="present")
        ranking, _ = apply_policy([item], {}, self.config)
        self.assertNotIn("sticker", ranking[0]["attribute_scores"])
        ranking, _ = apply_policy([item], {"sticker_status": "absent"}, self.config)
        self.assertEqual(ranking[0]["attribute_scores"]["sticker"], 0)

    def test_config_changes_decision(self):
        item = self.candidate(0, ["blue"], .1)
        constraints = {"colors": ["blue"]}
        self.config["decision"]["min_score"] = .99
        _, decision = apply_policy([item], constraints, self.config)
        self.assertEqual(decision["status"], "needs_confirmation")
        self.config["decision"]["min_score"] = .1
        _, decision = apply_policy([item], constraints, self.config)
        self.assertEqual(decision["status"], "matched")

    def test_normalization_preserves_navy(self):
        self.assertEqual(canonical("\ud478\ub978\uc0c9"), "blue")
        self.assertEqual(canonical("\ub0a8\uc0c9"), "navy")
        self.assertEqual(canonical("smartphone"), "phone")

    def test_invalid_config_fails(self):
        for section, key, value in (("weights", "color", -1), ("decision", "min_score", float("nan")),
                                    ("weights", "semantic", 0)):
            config = copy.deepcopy(self.config)
            config[section][key] = value
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/"config.yaml"
                path.write_text(yaml.safe_dump(config), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_config(path)
