import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from robot.studio_extension import update_arrival as updater


class ArrivalUpdateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.bundle = Path(self.folder.name) / 'bundle'
        path = self.bundle / 'backend' / updater.MODULE
        path.parent.mkdir(parents=True)
        self.target = Path(updater.__file__).with_name('runtime').joinpath('saved_pose.py').read_text(encoding='utf-8')
        path.write_text(self.target, encoding='utf-8')
        self.manifest = {'backend_files': [updater.MODULE, 'runtime/saved_poses.json'],
                         'files': {'backend/runtime/saved_poses.json': 'pose-hash'}}
        self.installed = {'source': self.target,
                          'hashes': {updater.MODULE: hashlib.sha256(path.read_bytes()).hexdigest(),
                                     'runtime/saved_poses.json': 'pose-hash'}}

    def test_accepts_only_known_margin_versions(self):
        old = self.target.replace(updater.COMMENTS, '')
        variants = [self.target, old.replace('ARM_ARRIVAL_TOLERANCE = 5.0', 'ARM_ARRIVAL_TOLERANCE = 3.0'),
                    old.replace('ARM_ARRIVAL_TOLERANCE = 5.0\n', '').replace('<= ARM_ARRIVAL_TOLERANCE', '<= 1.5')]
        for source in variants:
            with self.subTest(source=source[:30]):
                self.assertTrue(updater.compatible_source(source, self.target))
                self.assertTrue(updater.compatible_source(source.replace('\n', '\r\n'), self.target))
        for changed in (self.target.replace('LIMIT = 10.0', 'LIMIT = 20.0'),
                        self.target.replace('TOLERANCE = 5.0', 'TOLERANCE = 8.0')):
            self.assertFalse(updater.compatible_source(changed, self.target))

    def test_rejects_other_robot_poses(self):
        self.installed['hashes']['runtime/saved_poses.json'] = 'other-robot'
        with self.assertRaisesRegex(RuntimeError, 'poses differ'):
            updater.check_sources(self.bundle, self.manifest, self.installed)

    def test_rejects_active_runtime_without_inspecting_or_writing_source(self):
        with patch.object(updater.install, 'preflight', return_value=self.manifest), \
             patch.object(updater.install, 'sessions', return_value=[{'session_name': 'active'}]), \
             patch.object(updater.install, 'docker') as docker:
            with self.assertRaisesRegex(RuntimeError, 'End Studio'):
                updater.update(self.bundle, True)
            docker.assert_not_called()

    def test_default_only_probes_and_does_not_copy_or_restart(self):
        with patch.object(updater.install, 'preflight', return_value=self.manifest), \
             patch.object(updater.install, 'sessions', return_value=[]), \
             patch.object(updater.install, 'docker', return_value=Mock(stdout=json.dumps(self.installed))) as docker:
            updater.update(self.bundle)
            self.assertEqual(docker.call_count, 1)
            self.assertEqual(docker.call_args.args[:2], ('exec', updater.install.CONTAINER))

    def test_apply_backs_up_and_atomically_replaces_only_one_module(self):
        with patch.object(updater.install, 'preflight', return_value=self.manifest), \
             patch.object(updater.install, 'sessions', return_value=[]), \
             patch.object(updater.install, 'docker') as docker:
            def respond(*args):
                if args[0] == 'cp' and args[1].endswith(':' + updater.install.BACKEND + '/' + updater.MODULE):
                    Path(args[2]).write_bytes((self.bundle / 'backend' / updater.MODULE).read_bytes())
                if 'sha256sum' in args:
                    return Mock(stdout=self.installed['hashes'][updater.MODULE] + ' file')
                return Mock(stdout=json.dumps(self.installed))
            docker.side_effect = respond
            updater.update(self.bundle, True)
            calls = [call.args for call in docker.call_args_list]
            self.assertEqual(sum(args[0] == 'cp' for args in calls), 2)
            self.assertEqual(sum('os.replace(' in str(args) for args in calls), 1)
            self.assertFalse(any(args[0] in ('restart', 'stop') for args in calls))

    def test_session_appearing_after_probe_cancels_before_copy(self):
        with patch.object(updater.install, 'preflight', return_value=self.manifest), \
             patch.object(updater.install, 'sessions', side_effect=[[], ['new-session']]), \
             patch.object(updater.install, 'docker', return_value=Mock(stdout=json.dumps(self.installed))) as docker:
            with self.assertRaisesRegex(RuntimeError, 'appeared'):
                updater.update(self.bundle, True)
            self.assertEqual(docker.call_count, 1)
