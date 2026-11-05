"""Home 후보 저장의 읽기 전용 경계와 상태 변화 중단 시험."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.robot_home_snapshot import capture, NAMES


class ReadOnlyClient:
    def __init__(self):
        self.calls = []
        self.status_calls = 0
        self.position = [0., 0., 0., 0., 0., 50.]
        self.drift = False
        self.change_at = None
        self.running = False

    def rpc(self, operation):
        if operation != "status":
            raise AssertionError("제어 요청 금지")
        self.calls.append(operation)
        self.status_calls += 1
        epoch = 2 if self.change_at is None or self.status_calls < self.change_at else 3
        return {"ok": True, "session": "test-owner", "epoch": epoch,
                "stop_requested": not self.running, "hold_commanded": True}

    def positions(self):
        if self.drift:
            self.position[0] += .1
        return list(self.position)


class HomeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "candidate.json"
        self.client = ReadOnlyClient()
        self.reference = {"serial": "5B91030622", "calibration": {name: {"id": i+1} for i, name in enumerate(NAMES)}}

    def capture(self):
        return capture(self.client, self.path, self.reference, sleep=lambda seconds: None)

    def test_stationary_pose_is_candidate_only_and_never_commands_motion(self):
        result = self.capture()
        profile = json.loads(self.path.read_text())
        self.assertEqual(result["result"], "HOME_CANDIDATE_SAVED")
        self.assertEqual(set(self.client.calls), {"status"})
        self.assertFalse(profile["home_approved"])
        self.assertFalse(profile["path_verified"])
        self.assertFalse(profile["board_calibration_checked_by_capture"])
        self.assertEqual(profile["movement_commands_sent"], 0)
        self.assertEqual(profile["positions"], self.client.position)

    def test_running_owner_does_not_save(self):
        self.client.running = True
        with self.assertRaises(RuntimeError):
            self.capture()
        self.assertFalse(self.path.exists())

    def test_epoch_change_does_not_save(self):
        self.client.change_at = 5
        with self.assertRaises(RuntimeError):
            self.capture()
        self.assertFalse(self.path.exists())

    def test_drifting_pose_does_not_save(self):
        self.client.drift = True
        with self.assertRaisesRegex(RuntimeError, "자세 변화"):
            self.capture()
        self.assertFalse(self.path.exists())

    def test_wrong_device_reference_does_not_query_owner(self):
        self.reference["serial"] = "another-device"
        with self.assertRaises(RuntimeError):
            self.capture()
        self.assertEqual(self.client.calls, [])
        self.assertFalse(self.path.exists())

    def test_existing_file_is_preserved(self):
        self.path.write_text("keep existing candidate")
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertEqual(self.path.read_text(), "keep existing candidate")


    def test_wrong_preview_session_or_epoch_never_saves(self):
        for session, epoch in (("old-owner", 2), ("test-owner", 1)):
            with self.assertRaisesRegex(RuntimeError, "명령 세대"):
                capture(self.client, self.path, self.reference, sleep=lambda seconds: None,
                        expected_session=session, expected_epoch=epoch)
            self.assertFalse(self.path.exists())
