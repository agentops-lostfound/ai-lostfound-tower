import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import json

from robot.studio_extension import update_taught as updater


class TaughtUpdateTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'backend_files': ['runtime/saved_pose.py', 'runtime/saved_poses.json'],
            'files': {'backend/runtime/saved_pose.py': 'new-code', 'backend/runtime/saved_poses.json': 'new-poses'},
            'previous_backend_sets': [{'runtime/saved_pose.py': 'old-code', 'runtime/saved_poses.json': 'old-poses'}]}
        self.old = self.manifest['previous_backend_sets'][0]
        self.target = {n: self.manifest['files']['backend/' + n] for n in self.manifest['backend_files']}

    def run_update(self, *, apply=False, installed=None, sessions=None):
        installed = self.old if installed is None else installed
        with patch.object(updater.install, 'preflight', return_value=self.manifest), \
             patch.object(updater.install, 'sessions', side_effect=sessions or [[], []]), \
             patch.object(updater, 'check_local_files'), \
             patch.object(updater.install, 'docker', return_value=Mock(stdout=json.dumps(installed))) as docker, \
             patch.object(updater.install, 'backup_and_apply') as install:
            updater.update(Path('bundle'), apply)
            return docker, install

    def test_only_complete_known_backend_pose_pairs_are_accepted(self):
        self.assertEqual(updater.check_installed(self.manifest, self.old), self.target)
        self.assertEqual(updater.check_installed(self.manifest, self.target), self.target)
        for hashes in ({**self.old, 'runtime/saved_poses.json': 'custom-teaching'},
                       {**self.old, 'runtime/saved_pose.py': 'new-code'}, {}):
            with self.assertRaises(RuntimeError):
                updater.check_installed(self.manifest, hashes)

    def test_default_only_reads(self):
        docker, install = self.run_update()
        self.assertEqual(docker.call_count, 1)
        install.assert_not_called()

    def test_apply_reuses_complete_backup_with_checked_old_hashes(self):
        _, install = self.run_update(apply=True)
        self.assertEqual(install.call_args.args[1]['original_backend'], self.old)

    def test_already_installed_does_not_write_or_restart(self):
        _, install = self.run_update(apply=True, installed=self.target)
        install.assert_not_called()

    def test_active_or_new_runtime_is_rejected(self):
        for sessions in ([[{'session': 'active'}]], [[], [{'session': 'new'}]]):
            with self.subTest(sessions=sessions), self.assertRaises(RuntimeError):
                self.run_update(apply=True, sessions=sessions)

    def test_local_teaching_mismatch_prevents_even_inspecting_installed_backend(self):
        with patch.object(updater.install, 'preflight', return_value=self.manifest), \
             patch.object(updater.install, 'sessions', return_value=[]), \
             patch.object(updater, 'check_local_files', side_effect=RuntimeError('teaching differs')), \
             patch.object(updater.install, 'docker') as docker:
            with self.assertRaises(RuntimeError):
                updater.update(Path('bundle'), True)
            docker.assert_not_called()
