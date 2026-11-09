import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from robot.joint_motion import JOINTS
from robot.sequence_experiment import SequenceExperiment
from robot.sequence_panel import make_server


class ExperimentFixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'poses.json'
        values = {name + '.pos': 0.0 for name in JOINTS}
        poses = {name: dict(values) for name in ['home', 'close', 'open', 'outlet_return_1', *[f'pose_{n}' for n in range(1, 9)]]}
        self.path.write_text(json.dumps(poses), encoding='utf-8')
        self.motion = Mock()
        self.motion.stop.return_value = True
        self.model = SequenceExperiment(self.path, motion=self.motion)
        self.addCleanup(self.model.close)

    def wait(self):
        if self.model.worker:
            self.model.worker.join(2)
            self.assertFalse(self.model.worker.is_alive())
        if self.model.stop_worker:
            self.model.stop_worker.join(2)


class ExperimentTests(ExperimentFixture):
    def test_startup_prepares_without_connection_or_movement(self):
        with patch('subprocess.Popen') as process:
            model = SequenceExperiment(self.path, motion=self.motion, live=True)
            self.assertFalse(model.snapshot()['connected'])
            process.assert_not_called()
        self.motion.move.assert_not_called()

    def test_full_sequence_waits_and_keeps_duplicate_return_pose(self):
        self.model.prepare('R3-2', 4)
        self.model.start('all', 0, True)
        self.wait()
        self.assertEqual([c.args[0] for c in self.motion.move.call_args_list],
                         ['pose_6', 'outlet_return_1', 'close', 'open', 'outlet_return_1', 'home'])
        self.assertTrue(all(c.args[1] == 4 for c in self.motion.move.call_args_list))
        self.assertEqual(self.model.snapshot()['statuses'], ['도착'] * 6)

    def test_single_selected_step_does_not_run_next(self):
        self.model.start('step', 3, True)
        self.wait()
        self.motion.move.assert_called_once()
        self.assertEqual(self.motion.move.call_args.args[0], 'open')
        self.assertEqual(self.model.snapshot()['statuses'].count('도착'), 1)

    def test_unapproved_or_invalid_run_never_moves(self):
        for args in [('all', 0, False), ('bad', 0, True), ('step', -1, True), ('step', True, True)]:
            with self.assertRaises(ValueError):
                self.model.start(*args)
        self.motion.move.assert_not_called()

    def test_mid_sequence_error_halts_and_requires_reprepare(self):
        self.motion.move.side_effect = [None, RuntimeError('blocked')]
        self.model.start('all', 0, True)
        self.wait()
        self.assertEqual(self.motion.move.call_count, 2)
        self.assertTrue(self.model.snapshot()['halted'])
        with self.assertRaises(ValueError):
            self.model.start('all', 0, True)
        self.motion.stop.assert_called_once()

    def test_stop_interrupts_pending_stage_and_blocks_later_stages(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.motion.move.side_effect = lambda *args: (entered.set(), release.wait(2))
        self.motion.stop.side_effect = lambda: (release.set() or True)
        self.model.start('all', 0, True)
        self.assertTrue(entered.wait(1))
        with self.assertRaises(ValueError):
            self.model.prepare('R1-2', 3)
        self.model.request_stop()
        self.wait()
        self.assertEqual(self.motion.move.call_count, 1)
        self.assertNotIn('도착', self.model.snapshot()['statuses'])

    def test_stale_browser_lease_requests_stop(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.motion.move.side_effect = lambda *args: release.wait(2)
        self.motion.stop.side_effect = lambda: (release.set() or True)
        model = SequenceExperiment(self.path, motion=self.motion, lease_seconds=0.04)
        self.addCleanup(model.close)
        model.start('all', 0, True)
        model.worker.join(2)
        self.assertFalse(model.worker.is_alive())
        self.assertTrue(model.halted)

    def test_db_target_replaces_start_pose_without_modifying_db(self):
        target = {'ok': True, 'slot_id': 'R4-2', 'pose_name': 'pose_8', 'item_id': 'A-W31', 'number': 8}
        self.model.prepare(None, 5, target)
        self.assertEqual(self.model.snapshot()['sequence'][0], 'pose_8')
        self.assertIn('A-W31', self.model.snapshot()['source'])
        self.motion.move.assert_not_called()

    def test_live_mode_requires_feedback_and_hold_before_run(self):
        model = SequenceExperiment(self.path, motion=self.motion, live=True)
        self.addCleanup(model.close)
        with self.assertRaises(ValueError):
            model.start('all', 0, True)
        model.set_connected(True, 'test')
        model.observe({'event': 'observation', 'data': {n + '.pos': 0.0 for n in JOINTS}})
        model.observe({'event': 'state', 'data': {'follower_source': 'teleop'}})
        with self.assertRaises(ValueError):
            model.start('all', 0, True)
        self.motion.move.assert_not_called()


class PanelHttpTests(ExperimentFixture):
    def setUp(self):
        super().setUp()
        self.server = make_server(self.model, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        status, page = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.token = re.search(r"const TOKEN='([^']+)'", page).group(1)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, data=None, headers=None):
        client = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            client.request(method, path, body=None if data is None else json.dumps(data), headers=headers or {})
            response = client.getresponse()
            return response.status, response.read().decode('utf-8')
        finally:
            client.close()

    def test_http_rejects_missing_token_foreign_origin_and_host(self):
        command = {'mode': 'all', 'index': 0, 'approved': True}
        self.assertEqual(self.request('POST', '/api/run', command)[0], 403)
        self.assertEqual(self.request('POST', '/api/run', command, {'X-Sequence-Token': self.token, 'Origin': 'https://other.invalid'})[0], 403)
        self.assertEqual(self.request('GET', '/', headers={'Host': 'other.invalid'})[0], 403)
        self.motion.move.assert_not_called()

    def test_http_authenticated_step_and_state(self):
        headers = {'X-Sequence-Token': self.token}
        self.assertEqual(self.request('POST', '/api/run', {'mode': 'step', 'index': 0, 'approved': False}, headers)[0], 400)
        self.assertEqual(self.request('POST', '/api/run', {'mode': 'step', 'index': 0, 'approved': True}, headers)[0], 200)
        self.wait()
        status, body = self.request('GET', '/api/state', headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['statuses'][0], '도착')
        self.assertEqual(len(json.loads(body)['targets']), 6)
        self.motion.move.assert_called_once()
