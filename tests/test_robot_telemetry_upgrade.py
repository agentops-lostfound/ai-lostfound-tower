"""진단 연결부 갱신의 보존·복구·활성 소유자 차단 시험."""
from pathlib import Path
from unittest.mock import patch
import unittest

from tests import test_robot_patch_manager as fixtures
from tools import manage_robot_owner_patch as manager
from tools import upgrade_robot_owner_telemetry as telemetry


class TelemetryUpgradeTests(unittest.TestCase):
    setUp = fixtures.PatchManagerTests.setUp
    make_backup = fixtures.PatchManagerTests.make_backup

    def prepare(self):
        self.make_backup()
        manager.apply(self.backup, self.transport)
        self.original_bridge = (self.transport / telemetry.BRIDGE).read_bytes()
        self.new_bridge = Path(self.temp.name) / "bridge.py"
        self.new_bridge.write_text('SCHEMA = "lf-pan-goal-readback-v1"\n')
        self.output = Path(self.temp.name) / "upgrade"
        self.guard = patch.object(telemetry, "require_idle")
        self.idle_guard = self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_upgrade_preserves_original_backup_and_supports_rollback(self):
        self.prepare()
        result = telemetry.upgrade(self.candidate, self.backup, self.new_bridge, self.output)
        self.assertEqual(manager.check(result["container_candidate"], self.transport)[2], "ALREADY_INSTALLED")
        self.assertEqual((self.backup / telemetry.BRIDGE).read_bytes(), self.original_bridge)
        manager.rollback(result["container_backup"], self.transport)
        self.assertEqual((self.transport / manager.FILES[0]).read_bytes(), self.original)

    def test_undo_restores_previous_bridge(self):
        self.prepare()
        result = telemetry.upgrade(self.candidate, self.backup, self.new_bridge, self.output)
        telemetry.undo(self.backup, result["container_candidate"])
        self.assertEqual(manager.check(self.candidate, self.transport)[2], "ALREADY_INSTALLED")

    def test_busy_owner_or_unknown_change_blocks_upgrade(self):
        self.prepare()
        self.idle_guard.side_effect = RuntimeError("busy")
        with self.assertRaises(RuntimeError):
            telemetry.upgrade(self.candidate, self.backup, self.new_bridge, self.output)
        self.assertFalse(self.output.exists())
        self.idle_guard.side_effect = None
        (self.transport / telemetry.BRIDGE).write_text("external_change = True\n")
        with self.assertRaises(RuntimeError):
            telemetry.upgrade(self.candidate, self.backup, self.new_bridge, self.output)
        self.assertEqual((self.transport / telemetry.BRIDGE).read_text(), "external_change = True\n")

    def test_failed_verification_restores_previous_bridge(self):
        self.prepare()
        real_check = telemetry.check
        def failing(candidate, transport):
            if Path(candidate) == self.output / "candidate":
                raise OSError("verification failure")
            return real_check(candidate, transport)
        with patch.object(telemetry, "check", side_effect=failing):
            with self.assertRaises(OSError):
                telemetry.upgrade(self.candidate, self.backup, self.new_bridge, self.output)
        self.assertEqual((self.transport / telemetry.BRIDGE).read_bytes(), self.original_bridge)
