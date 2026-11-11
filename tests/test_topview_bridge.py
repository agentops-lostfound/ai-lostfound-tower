"""탑뷰 비교기는 실물/DB/GPU 없이 의미 있는 상태 경계를 검증한다."""
import copy
import unittest
from unittest.mock import patch

from vision.topview_bridge.reconcile import SLOTS, compare, layout_digest, validate_regions


class TopviewBridgeTest(unittest.TestCase):
    def setUp(self):
        self.config = {"image_size_px": [800, 400], "boundary_margin_px": 10,
                       "regions": {f"R{col}-{row}": [(col-1)*200, (row-1)*200, col*200, row*200]
                                   for col in range(1, 5) for row in (1, 2)}}
        self.db = {"sections": [{"code": f"R{col}", "slots": [
            {"slot_id": f"R{col}-{row}", "item": None} for row in (1, 2)]} for col in range(1, 5)]}

    def obj(self, name="R4-2", quality="accepted", category="lip_balm"):
        x1, y1, _, _ = self.config["regions"][name]
        return {"bbox_px": [x1+70, y1+40, x1+130, y1+160], "center_px": [x1+100, y1+100],
                "quality": quality, "category": category}

    def item(self, name, status="본센터 보관", category="립밤"):
        for section in self.db["sections"]:
            for slot in section["slots"]:
                if slot["slot_id"] == name:
                    slot["item"] = {"item_id": "A-TEST", "status": status, "category": category}

    def check(self, objects=(), **kwargs):
        observation = {"objects": list(objects), "captured_size": [800, 400]}
        return {row["slot_id"]: row for row in compare(observation, self.db, self.db, self.config, **kwargs)["slots"]}

    def test_empty_and_occupied_matches_never_verify_identity(self):
        self.item("R4-2")
        rows = self.check([self.obj()])
        self.assertEqual({row["state"] for row in rows.values()}, {"count_match"})
        self.assertFalse(rows["R4-2"]["identity_verified"])

    def test_moved_item_produces_missing_and_unexpected(self):
        self.item("R4-1")
        rows = self.check([self.obj("R4-2")])
        self.assertEqual(rows["R4-1"]["state"], "missing_candidate")
        self.assertEqual(rows["R4-2"]["state"], "unexpected_candidate")

    def test_review_is_not_silently_counted_as_empty(self):
        rows = self.check([self.obj(quality="review")])
        self.assertEqual(rows["R4-2"]["state"], "ambiguous")
        self.assertEqual(rows["R4-2"]["detected_count"], 0)

    def test_boundary_affects_both_slots(self):
        obj = self.obj()
        obj.update(bbox_px=[650, 175, 750, 225], center_px=[700, 200])
        rows = self.check([obj])
        self.assertEqual(rows["R4-1"]["state"], "ambiguous")
        self.assertEqual(rows["R4-2"]["state"], "ambiguous")

    def test_multiple_and_wrong_category(self):
        self.item("R4-2")
        self.assertEqual(self.check([self.obj(), self.obj()])["R4-2"]["state"], "multiple")
        self.assertEqual(self.check([self.obj(category="phone")])["R4-2"]["state"], "category_mismatch")

    def test_returning_assignment_does_not_expect_a_physical_item(self):
        for status in ("반환 중", "인계 대기", "반환 보류", "새로운 미확인 상태"):
            self.item("R4-2", status=status)
            row = self.check()["R4-2"]
            self.assertEqual(row["state"], "transition")
            self.assertIsNone(row["expected_count"])
        self.assertTrue(all(row["state"] == "transition" for row in self.check(busy=True).values()))

    def test_model_phone_and_db_mock_phone_share_category(self):
        self.item("R1-1", category="모형폰")
        self.assertEqual(self.check([self.obj("R1-1", category="phone")])["R1-1"]["state"], "count_match")

    def test_db_changed_during_inference_defers_all_slots(self):
        before = copy.deepcopy(self.db)
        self.item("R4-2")
        result = compare({"objects": [], "captured_size": [800, 400]}, before, self.db, self.config)
        self.assertTrue(result["db_changed"])
        self.assertEqual({row["state"] for row in result["slots"]}, {"unavailable"})
        self.assertEqual(layout_digest({**self.db, "received_at": "later"}), layout_digest(self.db))

    def test_no_db_and_resolution_mismatch_never_match(self):
        result = compare({"objects": [], "captured_size": [1280, 720]}, None, self.db, self.config)
        self.assertTrue(all(row["state"] == "unavailable" for row in result["slots"]))
        rows = self.check(unavailable="카메라 이동")
        self.assertTrue(all(row["state"] == "unavailable" for row in rows.values()))

    def test_overlapping_or_missing_regions_rejected(self):
        config = copy.deepcopy(self.config)
        config["regions"]["R4-2"] = config["regions"]["R4-1"]
        with self.assertRaises(ValueError):
            validate_regions(config)
        config["regions"].pop(SLOTS[0])
        with self.assertRaises(ValueError):
            validate_regions(config)

    def test_calibration_uses_frozen_photo_and_rejects_motion(self):
        try:
            import numpy as np
            from vision.topview_bridge.server import Bridge
        except ImportError:
            self.skipTest("로컬 화면 의존성 없음")
        import tempfile
        import threading
        import time
        from pathlib import Path
        bridge = Bridge.__new__(Bridge)
        bridge.lock = threading.RLock()
        bridge.config = {**copy.deepcopy(self.config), "camera_id": "topview"}
        bridge.frame = np.zeros((400, 800, 3), dtype=np.uint8)
        bridge.jpeg = b"frozen-jpeg"
        bridge.frame_at = "2026-11-11T00:00:00+00:00"
        bridge.frame_tick = time.monotonic()
        bridge.camera_error = None
        bridge.analyzing = False
        bridge.calibration_frames = {}
        reference = {"1": [[100, 100], [130, 100], [130, 130], [100, 130]]}
        moved = {"1": [[150, 100], [180, 100], [180, 130], [150, 130]]}
        with tempfile.TemporaryDirectory() as directory:
            bridge.config_path = Path(directory) / "config.json"
            with patch("vision.topview_bridge.server.anchors", return_value=reference):
                frozen = bridge.calibration_snapshot()
            with patch("vision.topview_bridge.adapters.anchors", return_value=moved):
                with self.assertRaisesRegex(ValueError, "이동"):
                    bridge.save_regions(bridge.config["regions"], frozen["reference_id"])
            self.assertFalse(bridge.config_path.exists())
            with patch("vision.topview_bridge.adapters.anchors", return_value=reference):
                bridge.save_regions(bridge.config["regions"], frozen["reference_id"])
            self.assertTrue(bridge.config_path.exists())


if __name__ == "__main__":
    unittest.main()
