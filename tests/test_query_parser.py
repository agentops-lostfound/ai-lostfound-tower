import copy
import unittest
from matching.query_parser import validate_output, guard_decision


class QueryParserTests(unittest.TestCase):
    def setUp(self):
        self.valid = {"features": {"category": "wallet", "colors": ["navy"],
                      "sticker_status": "unknown", "free_text": "A scuffed corner."},
                      "needs_clarification": False, "warnings": []}

    def test_unmentioned_sticker_remains_unknown(self):
        self.assertEqual(validate_output(self.valid)["features"]["sticker_status"], "unknown")

    def test_normalizes_without_merging_blue_navy(self):
        self.valid["features"]["colors"] = ["navy blue", "blue", "navy"]
        self.assertEqual(validate_output(self.valid)["features"]["colors"], ["navy", "blue"])

    def test_warnings_force_clarification(self):
        self.valid["warnings"] = ["Color is uncertain."]
        self.assertTrue(validate_output(self.valid)["needs_clarification"])

    def test_uncertain_query_blocks_match_and_no_match(self):
        for status in ("matched", "no_match"):
            guarded = guard_decision({"status": status, "selected_id": 2}, {"needs_clarification": True})
            self.assertEqual(guarded["status"], "needs_confirmation")
            self.assertIsNone(guarded["selected_id"])
        guarded = guard_decision({"status": "matched", "selected_id": 2},
                                 {"needs_clarification": False, "requires_review": True})
        self.assertEqual(guarded["status"], "needs_confirmation")
        self.assertIn("unvalidated_query_parser", guarded["reasons"])

    def test_invalid_schema_and_non_english_rejected(self):
        for key, value in (("free_text", "\ubcc4"), ("colors", "blue"),
                           ("category", "made_up"), ("sticker_status", "maybe")):
            item = copy.deepcopy(self.valid)
            item["features"][key] = value
            with self.assertRaises(ValueError):
                validate_output(item)
        self.valid["extra"] = 1
        with self.assertRaises(ValueError):
            validate_output(self.valid)
