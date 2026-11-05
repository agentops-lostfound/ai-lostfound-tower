"""Docker 권한 경계와 준비 실패 시 적용 불가 상태 시험."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_robot_owner_trial as trial


class TrialPreparationTests(unittest.TestCase):
    def test_only_manager_command_requests_container_root(self):
        record = {"container_dir": "/tmp/lf-owner-trial-test",
                  "container_backup": "/app/storage/patches/lf-owner-safety-test"}
        with patch.object(trial, "execute", return_value=json.dumps({"result": "READY_NOT_INSTALLED"})) as execute:
            trial.manager(record, "check")
        command = execute.call_args.args
        self.assertEqual(command[:6], ("docker", "exec", "--user", "0", trial.CONTAINER, "python"))
        self.assertNotIn("--privileged", command)

    def test_failed_idle_check_does_not_create_applicable_trial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root / "existing-candidate"
            candidate.mkdir()
            marker = candidate / "keep.txt"
            marker.write_text("existing candidate")
            with patch.object(trial, "ROOT", root), \
                 patch.object(trial, "read_candidate"), \
                 patch.object(trial, "execute") as execute, \
                 patch.object(trial, "manager", side_effect=[
                     {"result": "READY_NOT_INSTALLED"}, RuntimeError("permission denied")
                 ]) as manager:
                with self.assertRaisesRegex(RuntimeError, "permission denied"):
                    trial.prepare(candidate)
            self.assertEqual([call.args[1] for call in manager.call_args_list], ["check", "backup"])
            self.assertEqual(list((root / "outputs").rglob("trial.json")), [])
            self.assertFalse(any("apply" in call.args for call in execute.call_args_list))
            self.assertEqual(marker.read_text(), "existing candidate")
