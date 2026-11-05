"""Home 목표 교체·이력·잘못된 장비/보정/값 차단 시험. 장비 접근 없음."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robot import home_profiles as home


class HomeProfileTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.store = self.root / "home"
        self.default = home.load_home(self.store)
        self.candidate = self.root / "candidate.json"
        self.data = {**deepcopy(self.default), "schema": "lf-home-candidate-v1",
                     "candidate_only": True, "observation_span_normalized": [0.]*6}
        self.write_candidate()

    def write_candidate(self):
        self.candidate.write_text(json.dumps(self.data), encoding="utf-8")

    def test_selects_user_folded_pose_without_enabling_motion(self):
        result = home.select_candidate(self.candidate, self.store)
        active = home.load_home(self.store)
        self.assertEqual(result["result"], "HOME_POSE_CONFIGURED")
        self.assertEqual(active["positions"], self.default["positions"])
        self.assertTrue(active["pose_selected"])
        self.assertFalse(active["path_verified"])
        self.assertFalse(active["motion_enabled"])
        self.assertEqual(len(list((self.store / "history").glob("*.json"))), 1)

    def test_changed_pose_increments_revision_and_preserves_previous(self):
        home.select_candidate(self.candidate, self.store)
        self.data["positions"][0] += .1
        self.write_candidate()
        home.select_candidate(self.candidate, self.store, name="다음 대기 자세")
        active = home.load_home(self.store)
        self.assertEqual(active["revision"], self.default["revision"] + 1)
        self.assertEqual(active["positions"], self.data["positions"])
        history = [home.read_json(p) for p in (self.store / "history").glob("*.json")]
        self.assertIn(self.default["positions"], [p["positions"] for p in history])
        self.assertFalse(active["path_verified"])

    def test_repeating_same_selection_does_not_revise_or_duplicate_history(self):
        first = home.select_candidate(self.candidate, self.store)
        second = home.select_candidate(self.candidate, self.store)
        self.assertEqual(second["result"], "HOME_POSE_ALREADY_CONFIGURED")
        self.assertEqual(first["revision"], second["revision"])
        self.assertEqual(len(list((self.store / "history").glob("*.json"))), 1)

    def test_wrong_device_calibration_or_invalid_numbers_preserve_active(self):
        home.select_candidate(self.candidate, self.store)
        active = (self.store / "active.json").read_bytes()
        for key, value in (("serial", "wrong"), ("calibration_reference_sha256", "0"*64),
                           ("positions", [float("nan")]*6), ("joint_order", list(reversed(home.NAMES)))):
            data = deepcopy(self.data)
            data[key] = value
            self.candidate.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                home.select_candidate(self.candidate, self.store)
            self.assertEqual((self.store / "active.json").read_bytes(), active)

    def test_history_failure_does_not_replace_active(self):
        home.select_candidate(self.candidate, self.store)
        active = (self.store / "active.json").read_bytes()
        self.data["positions"][0] += .1
        self.write_candidate()
        with patch.object(home, "atomic_json", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                home.select_candidate(self.candidate, self.store)
        self.assertEqual((self.store / "active.json").read_bytes(), active)
        self.assertFalse((self.store / ".setting.lock").exists())

    def test_existing_lock_blocks_update(self):
        self.store.mkdir()
        (self.store / ".setting.lock").write_text("other writer")
        with self.assertRaises(RuntimeError):
            home.select_candidate(self.candidate, self.store)
        self.assertFalse((self.store / "active.json").exists())

    def test_manual_execution_flag_is_not_accepted(self):
        home.select_candidate(self.candidate, self.store)
        file = self.store / "active.json"
        profile = home.read_json(file)
        profile["motion_enabled"] = True
        file.write_text(json.dumps(profile))
        with self.assertRaises(ValueError):
            home.load_home(self.store)
