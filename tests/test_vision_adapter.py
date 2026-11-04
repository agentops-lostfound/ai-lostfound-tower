"""Contract-focused tests for LF-3 adapter; no camera or GPU needed."""
import copy
import unittest

from agents.contracts import validate_detection, UNKNOWN, NONE
from vision.adapter import VisionPart, adapt_report


def fixture():
    return {
        "sequence": {"status": "complete"},
        "calibration": {"valid": True},
        "objects": [{
            "id": 7, "bbox": [10.0, 20.0, 50.0, 80.0],
            "center_px": [30.0, 50.0],
            "center_world_mm": [120.0, 230.0],
            "calibration_valid": True,
            "confidence": 0.81,
            "qwen": {"status": "ok", "features": {
                "category": "wallet", "colors": ["black"], "shape": "card holder",
                "materials": ["leather"], "logos_or_text": ["1234 5678"],
                "sticker_status": "present",
                "stickers": [{"shape": "star", "position": "front"}],
                "distinctive_features": [],
            }}
        }]
    }


class VisionAdapterTests(unittest.TestCase):
    def test_contract_and_pixel_not_mm(self):
        item = adapt_report(fixture())[0]
        self.assertEqual(item["object_id"], 7)
        self.assertEqual(item["center"], [30.0, 50.0])
        self.assertEqual(item["box"], [10.0, 20.0, 50.0, 80.0])
        self.assertEqual(item["features"]["category"], "지갑")
        self.assertEqual(item["features"]["color"], "검정")
        self.assertEqual(item["features"]["confidence"], .81)
        self.assertEqual(validate_detection(item), [])

    def test_privacy_no_qwen_text_leak(self):
        item = adapt_report(fixture())[0]
        self.assertEqual(item["features"]["visible_text"], UNKNOWN)
        self.assertNotIn("1234", str(item))

    def test_unknown_and_absent_are_distinct(self):
        report = fixture()
        features = report["objects"][0]["qwen"]["features"]
        features["colors"] = ["black", "blue"]
        features["sticker_status"] = "absent"
        item = adapt_report(report)[0]
        self.assertEqual(item["features"]["color"], UNKNOWN)
        self.assertEqual(item["features"]["mark"], NONE)

    def test_reject_failed_partial_or_unsupported(self):
        for mutation in (
            lambda r: r["sequence"].update(status="failed"),
            lambda r: r["objects"][0]["qwen"].update(status="failed"),
            lambda r: r["objects"][0]["qwen"]["features"].update(category="smart_watch"),
            lambda r: r["objects"][0].update(confidence=float("nan")),
            lambda r: r["objects"][0].update(center_px=[float("inf"), 1]),
        ):
            report = fixture()
            mutation(report)
            self.assertEqual(adapt_report(report), [])

    def test_calibration_gate(self):
        report = fixture()
        report["calibration"]["valid"] = False
        self.assertEqual(adapt_report(report), [])
        self.assertEqual(len(adapt_report(report, require_calibration=False)), 1)

    def test_duplicates_fail_whole_scene(self):
        report = fixture()
        report["objects"].append(copy.deepcopy(report["objects"][0]))
        self.assertEqual(adapt_report(report), [])

    def test_provider_and_error_fallback(self):
        part = VisionPart(fixture)
        self.assertEqual(len(part.vision_topview()), 1)
        self.assertEqual(VisionPart(lambda: (_ for _ in ()).throw(OSError())).vision_topview(), [])
        with self.assertRaises(TypeError):
            VisionPart(None)


if __name__ == "__main__":
    unittest.main()
