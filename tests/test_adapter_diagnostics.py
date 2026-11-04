"""Diagnostic checks independent of Qwen, YOLO or physical robot."""
import copy
import unittest

from vision.adapter import adapt_report
from vision.adapter_diagnostics import diagnose_report


def sample(cat="phone", num=0):
    return {"id": num, "bbox": [1, 2, 101, 202], "center_px": [51, 102],
            "confidence": 0.9, "qwen": {"status": "ok", "features": {
                "category": cat, "colors": ["white"], "shape": "rectangular",
                "materials": ["plastic"], "stickers": [], "sticker_status": "absent",
                "logos_or_text": ["PRIVATE ID 123456"]}}}


def scene(*objects, status="complete", calibration=False):
    return {"sequence": {"status": status}, "calibration": {"valid": calibration},
            "objects": list(objects)}


class DiagnosticsTest(unittest.TestCase):
    def test_all_valid(self):
        report = scene(sample(), sample("usb", 1))
        d = diagnose_report(report)
        self.assertTrue(d["scene_complete"])
        self.assertEqual(d["actual_adapter_count"], 2)
        self.assertEqual(d["reason_counts"], {})
        self.assertNotIn("PRIVATE ID", str(d))

    def test_partial_is_not_sent_to_backend(self):
        report = scene(sample(), sample("smart_watch", 1), sample("wallet", 2))
        d = diagnose_report(report)
        self.assertEqual(d["accepted_preview_count"], 2)
        self.assertEqual(d["actual_adapter_count"], 0)
        self.assertFalse(d["scene_complete"])
        self.assertEqual(d["objects"][1]["reason"], "unsupported_category")
        self.assertEqual(adapt_report(report, require_calibration=False), [])

    def test_unknown_and_other(self):
        d = diagnose_report(scene(sample("unknown"), sample("other", 1)))
        self.assertEqual(d["reason_counts"], {"other_category": 1, "unknown_category": 1})

    def test_qwen_failure_and_incomplete(self):
        obj = sample()
        obj["qwen"] = {"status": "failed", "features": None, "error": "secret raw output"}
        d = diagnose_report(scene(obj, status="failed"))
        self.assertEqual(d["reason_counts"], {"qwen_failed": 1, "sequence_incomplete": 1})
        self.assertNotIn("secret", str(d))
        self.assertEqual(d["actual_adapter_count"], 0)

    def test_calibration_gate(self):
        report = scene(sample())
        d = diagnose_report(report, require_calibration=True)
        self.assertEqual(d["accepted_preview_count"], 1)
        self.assertEqual(d["actual_adapter_count"], 0)
        self.assertEqual(d["reason_counts"], {"calibration_unavailable": 1})

    def test_duplicate_id(self):
        d = diagnose_report(scene(sample(), copy.deepcopy(sample())))
        self.assertEqual(d["reason_counts"], {"duplicate_object_id": 1})
        self.assertEqual(d["actual_adapter_count"], 0)

    def test_invalid_coordinates(self):
        obj = sample()
        obj["center_px"] = [float("nan"), 3]
        d = diagnose_report(scene(obj))
        self.assertEqual(d["reason_counts"], {"invalid_center_px": 1})

    def test_empty_scene(self):
        d = diagnose_report(scene(status="no_detections"))
        self.assertEqual(d["detected_count"], 0)
        self.assertEqual(d["reason_counts"], {"no_detections": 1, "sequence_incomplete": 1})


if __name__ == "__main__":
    unittest.main()
