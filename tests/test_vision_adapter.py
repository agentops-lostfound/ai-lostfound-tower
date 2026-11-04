"""김건태 LF-3 시퀀스 결과(result_with_qwen.json) → 관제탑 vision 부품 변환 시험."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.backends import CompositeBackend, check_part  # noqa: E402
from agents.contracts import NONE, UNKNOWN, validate_detection  # noqa: E402
from agents.vision_adapter import SequenceFileVisionPart, adapt_report, to_features  # noqa: E402

WALLET = {"category": "wallet", "colors": ["dark brown"], "shape": "bifold", "materials": ["leather"],
          "logos_or_text": [], "sticker_status": "present",
          "stickers": [{"shape": "star", "position": "front corner"}], "distinctive_features": []}
PHONE = {"category": "phone", "colors": ["Black"], "shape": "rectangle", "materials": [], "logos_or_text": ["ABC"],
         "sticker_status": "absent", "stickers": [], "distinctive_features": []}


def report(status="complete"):
    """vision/sequence.py 결과와 같은 모양(김건태 브랜치 LF-3-yolo-aruco 기준)"""
    return {"sequence": {"status": status},
            "calibration": {"valid": True, "correspondence_count": 8, "max_reprojection_error_mm": 0.5},
            "objects": [
                {"id": 0, "class_name": "cell phone", "confidence": 0.83, "bbox": [10, 20, 110, 220],
                 "center_px": [60, 120], "center_world_mm": None, "qwen": {"status": "ok", "features": WALLET}},
                {"id": 1, "class_name": "cell phone", "confidence": 0.79, "bbox": [200, 30, 300, 230],
                 "center_px": [250, 130], "center_world_mm": [120.5, 80.25], "qwen": {"status": "ok", "features": PHONE}},
                {"id": 2, "class_name": "toothbrush", "confidence": 0.15, "bbox": [400, 50, 430, 120],
                 "center_px": [415, 85], "qwen": {"status": "failed", "features": None}},
                {"id": 3, "class_name": "bad", "confidence": 0.5, "bbox": [5, 5, 1, 1], "center_px": [3, 3],
                 "qwen": {"status": "ok", "features": PHONE}},            # 잘못된 박스 → 빠짐
            ]}


class ToFeaturesTest(unittest.TestCase):
    def test_wallet(self):
        f = to_features(WALLET, 0.834)
        self.assertEqual(f, {"category": "지갑", "color": "갈색", "shape": "bifold", "material": "leather",
                             "mark": "star sticker (front corner)", "visible_text": UNKNOWN, "confidence": 0.834})

    def test_phone_absent_sticker_and_text(self):
        f = to_features(PHONE, 0.79)
        self.assertEqual((f["category"], f["color"], f["mark"], f["visible_text"], f["material"]),
                         ("모형폰", "검정", NONE, "ABC", UNKNOWN))

    def test_unmapped_and_missing(self):
        self.assertEqual(to_features({**PHONE, "category": "other", "colors": ["pink"]}, 0.5)["category"], UNKNOWN)
        self.assertEqual(to_features({**PHONE, "category": "hand_cream"}, 0.5)["category"], "핸드크림")
        self.assertEqual(to_features({**PHONE, "category": "power_bank"}, 0.5)["category"], "보조배터리")
        self.assertEqual(to_features({**PHONE, "colors": ["purple"]}, 0.5)["color"], "기타")
        self.assertEqual(to_features({**PHONE, "colors": ["pink sand"]}, 0.5)["color"], "분홍")   # 11/4 분홍 추가
        self.assertTrue(all(v == UNKNOWN for k, v in to_features(None, 0.2).items() if k != "confidence"))
        self.assertEqual(to_features(None, 7)["confidence"], 1.0)


class AdaptReportTest(unittest.TestCase):
    def test_contract_shape(self):
        dets = adapt_report(report())
        self.assertEqual([d["vision_id"] for d in dets], [0, 1, 2])
        for d in dets:
            self.assertEqual(validate_detection(d), [])
        self.assertEqual(dets[1]["center_mm"], [120.5, 80.2])
        self.assertEqual(dets[2]["features"]["category"], UNKNOWN)   # Qwen 실패 → 확인 불가


class FilePartTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, sub, data, age=0):
        p = self.root / sub / "result_with_qwen.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(data), encoding="utf-8")
        t = time.time() - age
        os.utime(p, (t, t))
        return p

    def test_latest_file_in_folder(self):
        self.write("old", {"sequence": {"status": "complete"}, "objects": []}, age=60)
        self.write("new", report())
        part = SequenceFileVisionPart(self.root)
        self.assertEqual(len(part.vision_topview()), 3)
        self.assertEqual(check_part(part, "vision"), [])
        self.assertEqual(CompositeBackend(vision=part).sources()["vision_topview"], "SequenceFileVisionPart")

    def test_stale_running_missing_broken_give_empty(self):
        cases = [(self.write("a", report(), age=3600), "오래됨"),
                 (self.write("b", report(status="running")), "끝나지 않음"),
                 (self.root / "none.json", "없음")]
        for path, why in cases:
            part = SequenceFileVisionPart(path, max_age_s=600)
            self.assertEqual(part.vision_topview(), [], why)
            self.assertIn(why, part.last_reason)
        bad = self.root / "c" / "result_with_qwen.json"
        bad.parent.mkdir()
        bad.write_text("{깨진 json", encoding="utf-8")
        part = SequenceFileVisionPart(bad)
        self.assertEqual(part.vision_topview(), [])
        self.assertIn("읽기 실패", part.last_reason)


if __name__ == "__main__":
    unittest.main()


class CapturedAtTest(unittest.TestCase):
    """11/4: 결과에 촬영 시각(captured_at)이 있으면 그 값으로 나이를 센다(없으면 파일 저장 시각)."""

    def test_parse(self):
        from agents.vision_adapter import captured_age
        now = 1_793_760_000.0      # 2026-11-04 (UTC 기준 아무 시각)
        from datetime import datetime, timezone
        iso = datetime.fromtimestamp(now - 90, timezone.utc).isoformat()
        self.assertAlmostEqual(captured_age(iso, now), 90, delta=0.01)
        self.assertAlmostEqual(captured_age(iso.replace("+00:00", "Z"), now), 90, delta=0.01)
        for bad in (None, "", "어제", "2026-11-04T10:00:00", 123):
            self.assertIsNone(captured_age(bad, now), bad)
        future = datetime.fromtimestamp(now + 60, timezone.utc).isoformat()
        self.assertIsNone(captured_age(future, now))

    def test_part_uses_captured_at(self):
        import json
        import tempfile
        from datetime import datetime, timedelta, timezone
        from pathlib import Path
        from agents.vision_adapter import SequenceFileVisionPart
        from tools import mock_scene as ms
        with tempfile.TemporaryDirectory() as tmp:
            path = ms.write_report(tmp)
            report = json.loads(Path(path).read_text(encoding="utf-8"))
            report["captured_at"] = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
            Path(path).write_text(json.dumps(report), encoding="utf-8")       # 파일은 방금 저장(새것)
            part = SequenceFileVisionPart(path, max_age_s=180)
            self.assertEqual(part.vision_topview(), [])                         # 촬영은 400초 전 → 오래됨
            self.assertIn("촬영 4", part.last_reason)
            report["captured_at"] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
            Path(path).write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(len(part.vision_topview()), 7)


class CalibrationGateTest(unittest.TestCase):
    """11/4: 표식 2개(대응점 8개) + 오차 3mm 이하 + 물체별 calibration_valid 일 때만 center_mm. 아니면 로봇 안 움직임."""

    def obj(self, **kw):
        o = {"id": 0, "confidence": 0.8, "bbox": [10, 20, 110, 220], "center_px": [60, 120],
             "center_world_mm": [120.5, 80.25], "calibration_valid": True, "qwen": {"status": "ok", "features": WALLET}}
        o.update(kw)
        return o

    def dets(self, calibration, **kw):
        return adapt_report({"sequence": {"status": "complete"}, "calibration": calibration, "objects": [self.obj(**kw)]})

    def test_two_markers_pass(self):
        d = self.dets({"valid": True, "correspondence_count": 8, "max_reprojection_error_mm": 1.2})
        self.assertEqual(d[0]["center_mm"], [120.5, 80.2])

    def test_blocked_cases_keep_detection_without_mm(self):
        cases = [None, {"valid": False}, {"valid": True, "correspondence_count": 4},     # 표식 1개
                 {"valid": True}, {"valid": True, "correspondence_count": 8, "max_reprojection_error_mm": 4.5}]
        for c in cases:
            d = self.dets(c)
            self.assertEqual(len(d), 1, c)                 # 매칭용 검출은 남김
            self.assertNotIn("center_mm", d[0], c)          # 로봇 좌표는 없음
        ok = {"valid": True, "correspondence_count": 8}
        for kw in ({"calibration_valid": False}, {"center_world_mm": None}, {"center_world_mm": [float("nan"), 1]},
                   {"center_world_mm": [1]}):
            self.assertNotIn("center_mm", self.dets(ok, **kw)[0], kw)

    def test_part_reason_and_diagnosis(self):
        import json
        import tempfile
        from pathlib import Path
        from agents.vision_adapter import SequenceFileVisionPart
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "result_with_qwen.json"
            p.write_text(json.dumps({"sequence": {"status": "complete"}, "calibration": {"valid": True, "correspondence_count": 4},
                                     "objects": [self.obj()]}), encoding="utf-8")
            part = SequenceFileVisionPart(p, max_age_s=None)
            self.assertEqual(len(part.vision_topview()), 1)
            self.assertIn("표식 2개", part.last_reason)
            self.assertIsNotNone(part.last_diagnosis)       # 김건태 진단 연결
            # 참고: 김건태 진단은 calibration.valid 만 보고 표식 개수는 보지 않는다(11/4 기준) → 관제탑 검사가 더 엄격
            self.assertEqual(set(part.last_diagnosis), {"scene_complete", "calibration_valid", "detected_count", "reason_counts"})

    def test_flow_without_calibration_goes_to_staff(self):
        """보정 없는 탑뷰 결과로 반환 → 매칭은 되지만 로봇은 움직이지 않고 직원 확인."""
        from agents.backends import CompositeBackend
        from agents.supervisor import ReturnRequest, run_return
        from agents.tools import MockBackend
        from discord_ops.reporter import Reporter

        class V:
            def vision_topview(_):
                return adapt_report({"sequence": {"status": "complete"}, "calibration": {"valid": True, "correspondence_count": 4},
                                     "objects": [self_obj]})
        self_obj = self.obj()
        feats = to_features(WALLET, 0.8)
        mock = MockBackend(db={"A-1": {"status": "본센터 보관", "features": {k: v for k, v in feats.items() if k != "confidence"}}})
        be = CompositeBackend(vision=V(), fallback=mock)
        out = run_return(ReturnRequest("CAL1", "A-1"), be, Reporter())
        self.assertEqual(out.decision, "staff_check", out.reason)
        self.assertIn("작업대 좌표 없음", out.reason)
        self.assertFalse(mock.robot_moved())
