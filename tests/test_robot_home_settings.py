"""Home 미리보기/저장과 이동·정지 작업의 동시 실행 경계 시험."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from robot.home_profiles import load_home, select_candidate
from tools.robot_home_settings import HomeSettingsController
from tools.robot_stop_panel import HomeController


class StatusWorker:
    def __init__(self):
        self.epoch = 3
        self.stopped = True
        self.session = "owner"
        self.calls = []

    def request(self, operation, session=None):
        self.calls.append((operation, session))
        return {"ok": True, "session": self.session, "epoch": self.epoch,
                "stop_requested": self.stopped, "hold_commanded": self.stopped}


class HomeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Path(self.folder.name) / "home"
        self.file = Path(self.folder.name) / "candidate.json"
        self.profile = load_home(self.store)
        positions = list(self.profile["positions"])
        positions[0] += 4
        self.candidate = {
            **self.profile, "schema": "lf-home-candidate-v1", "candidate_only": True,
            "positions": positions, "observation_span_normalized": [0.] * 6,
            "owner_session": "owner", "epoch": 3, "movement_commands_sent": 0,
            "windows_file": str(self.file),
        }
        self.file.write_text(json.dumps(self.candidate))
        self.saved = []
        def save(candidate, name):
            self.saved.append(name)
            return select_candidate(candidate["windows_file"], self.store, name=name)
        self.status = StatusWorker()
        self.action_lock = threading.Lock()
        self.controller = HomeSettingsController(lambda session, epoch: dict(self.candidate), save,
            self.status, lambda: load_home(self.store), self.action_lock)
        self.addCleanup(self.controller.close)

    def capture(self):
        self.controller.capture("owner", 3, staff_confirmed=True)
        self.controller.thread.join(2)
        snapshot = self.controller.status()
        self.assertEqual(snapshot["state"], "preview")
        return snapshot["candidate_id"]

    def save(self, identity):
        return self.controller.save(identity, "owner", 3, name="보관함 옆 대기", staff_confirmed=True)

    def test_capture_previews_without_changing_home_and_save_preserves_history(self):
        identity = self.capture()
        self.assertEqual(self.saved, [])
        self.assertEqual(load_home(self.store), self.profile)
        result = self.save(identity)
        self.assertEqual(result["state"], "saved")
        self.assertEqual(result["movement_commands_sent"], 0)
        active = load_home(self.store)
        self.assertEqual(active["positions"], self.candidate["positions"])
        self.assertEqual(active["revision"], self.profile["revision"] + 1)
        self.assertFalse(active["path_verified"])
        self.assertFalse(active["motion_enabled"])
        self.assertEqual(len(list((self.store / "history").glob("*.json"))), 1)
        self.assertEqual(self.status.calls, [("status", None)])

    def test_save_requires_preview_confirmation_and_exact_candidate(self):
        with self.assertRaises(RuntimeError):
            self.save("unknown")
        identity = self.capture()
        with self.assertRaises(ValueError):
            self.controller.save(identity, "owner", 3, name="대기")
        with self.assertRaises(RuntimeError):
            self.save("unknown")
        self.assertEqual(self.saved, [])
        self.assertEqual(load_home(self.store), self.profile)

    def test_epoch_session_or_running_change_blocks_save(self):
        identity = self.capture()
        for values in ((4, "owner", True), (3, "another", True), (3, "owner", False)):
            self.status.epoch, self.status.session, self.status.stopped = values
            with self.assertRaises(RuntimeError):
                self.save(identity)
        self.assertEqual(self.saved, [])

    def test_saved_candidate_cannot_be_replayed(self):
        identity = self.capture()
        self.save(identity)
        with self.assertRaises(RuntimeError):
            self.save(identity)
        self.assertEqual(self.saved, ["보관함 옆 대기"])

    def test_capture_and_home_are_mutually_exclusive(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def capture(session, epoch):
            entered.set()
            release.wait(2)
            return dict(self.candidate)
        self.controller.capture_pose = capture
        self.controller.capture("owner", 3, staff_confirmed=True)
        self.assertTrue(entered.wait(1))
        home = HomeController(None, self.status, lambda: self.profile, self.action_lock)
        with self.assertRaises(RuntimeError):
            home.start("owner", 3, staff_confirmed=True)
        with self.assertRaises(RuntimeError):
            self.controller.capture("owner", 3, staff_confirmed=True)
        release.set()
        self.controller.thread.join(2)

    def test_existing_home_blocks_capture_and_save(self):
        identity = self.capture()
        self.action_lock.acquire()
        try:
            with self.assertRaises(RuntimeError):
                self.controller.capture("owner", 3, staff_confirmed=True)
            with self.assertRaises(RuntimeError):
                self.save(identity)
        finally:
            self.action_lock.release()
        self.assertEqual(self.saved, [])

    def test_capture_mismatch_or_failure_preserves_old_home(self):
        self.candidate["epoch"] = 4
        self.controller.capture("owner", 3, staff_confirmed=True)
        self.controller.thread.join(2)
        self.assertEqual(self.controller.status()["state"], "error")
        self.assertIsNone(self.controller.candidate)
        self.assertFalse(self.action_lock.locked())
        self.assertEqual(load_home(self.store), self.profile)
