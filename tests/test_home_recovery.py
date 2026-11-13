import json
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import Mock

from robot.home_recovery import home_path
from robot.remote_client import RemoteTowerRobot
from robot.remote_executor import Executor, make_server
from robot.tower_part import TowerRobot
from tests.sequence_fixtures import taught_poses


def snapshot(poses, pose='pose_7_target'):
    return {'state': {'connected': True, 'follower_source': 'hold', 'is_recording': False,
                      'saved_pose_status': 'stopped', 'saved_pose_name': pose},
            'positions': dict(poses[pose])}


class HomePathTests(unittest.TestCase):
    def setUp(self):
        self.poses = taught_poses()

    def test_each_pick_zone_retreats_to_its_approach_before_home(self):
        for number in range(1, 9):
            for suffix in ('', '_open', '_target', '_close'):
                name = f'pose_{number}{suffix}'
                self.assertEqual(home_path(snapshot(self.poses, name), self.poses), [f'pose_{number}', 'home'])

    def test_outlet_retreat_and_already_home(self):
        self.assertEqual(home_path(snapshot(self.poses, 'close'), self.poses), ['outlet_return_1', 'home'])
        self.assertEqual(home_path(snapshot(self.poses, 'home'), self.poses), ['home'])

    def test_foreign_position_and_unknown_path_are_rejected(self):
        current = snapshot(self.poses)
        current['positions']['shoulder_pan.pos'] = -80
        with self.assertRaises(ValueError):
            home_path(current, self.poses)
        current = snapshot(self.poses)
        current['state']['saved_pose_name'] = 'another_controller'
        with self.assertRaises(ValueError):
            home_path(current, self.poses)

    def test_teleop_recording_and_inflight_motion_are_rejected(self):
        for change in ({'follower_source': 'teleop'}, {'is_recording': True}, {'connected': False},
                       {'saved_pose_status': 'moving'}, {'saved_pose_status': 'holding_target'}):
            current = snapshot(self.poses)
            current['state'].update(change)
            with self.assertRaises(ValueError):
                home_path(current, self.poses)


class HomePartTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)/'poses.json'
        self.poses = taught_poses()
        self.path.write_text(json.dumps(self.poses), encoding='utf8')
        self.motion = Mock()
        self.motion.snapshot.return_value = snapshot(self.poses)
        self.part = TowerRobot(motion=self.motion, poses_path=self.path, environ={})

    def test_explicit_confirmation_preserves_gripper_until_approach(self):
        result = self.part.robot_home(empty_gripper_confirmed=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['completed'], ['pose_7', 'home'])
        self.assertEqual(self.motion.move.call_args_list[0].kwargs, {'include_gripper': False})
        self.assertEqual(self.motion.move.call_args_list[1].kwargs, {'include_gripper': True})

    def test_unconfirmed_or_cancelled_request_never_moves(self):
        self.assertFalse(self.part.robot_home()['ok'])
        self.part.cancelled.set()
        self.assertFalse(self.part.robot_home(empty_gripper_confirmed=True)['ok'])
        self.motion.move.assert_not_called()

    def test_legacy_home_only_acknowledges_an_observed_completed_home(self):
        self.motion.snapshot.return_value = snapshot(self.poses, 'home')
        result = self.part.robot_home()
        self.assertTrue(result['ok'])
        self.assertFalse(result['movement_sent'])
        self.motion.move.assert_not_called()
        current = snapshot(self.poses, 'home')
        current['positions']['gripper.pos'] += 8
        self.motion.snapshot.return_value = current
        self.assertFalse(self.part.robot_home()['ok'])
        self.motion.move.assert_not_called()

    def test_mid_recovery_failure_stops_without_going_home(self):
        self.motion.move.side_effect = RuntimeError('following error')
        self.motion.stop.return_value = True
        result = self.part.robot_home(empty_gripper_confirmed=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['stop_confirmed'])
        self.assertEqual(self.motion.move.call_count, 1)


class HomeHttpTests(unittest.TestCase):
    def setUp(self):
        self.backends = []
        self.entered, self.release = threading.Event(), threading.Event()
        self.block = False
        owner = self
        class Backend:
            error = ''
            def __init__(self):
                self.cancelled = threading.Event()
                owner.backends.append(self)
            def robot_home(self, *, empty_gripper_confirmed=False):
                owner.entered.set()
                if owner.block:
                    owner.release.wait(2)
                return {'ok': empty_gripper_confirmed and not self.cancelled.is_set()}
            def robot_stop(self):
                self.cancelled.set()
                owner.release.set()
                return {'ok': True}
        self.engine = Executor(Backend)
        self.token = secrets.token_urlsafe(32)
        self.server = make_server(self.engine, self.token, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = RemoteTowerRobot(url=f'http://127.0.0.1:{self.server.server_port}',
                                       token=self.token, expected_mode='simulation')
        self.addCleanup(self.close)

    def close(self):
        self.release.set()
        self.engine.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def test_stop_then_home_works_repeatedly_without_arming_pickup(self):
        for _ in range(2):
            self.assertTrue(self.client.robot_stop()['ok'])
            result = self.client.robot_home()
            self.assertTrue(result['ok'], result)
            self.assertFalse(self.engine.armed)
            self.assertFalse(self.client.faulted)
            self.assertFalse(self.client.robot_go_pose('pose_1', 'R1-1')['ok'])
        self.assertEqual(len(self.backends), 2)

    def test_home_preserves_existing_local_arm_on_repeated_requests(self):
        self.client.arm_local()
        for _ in range(2):
            self.assertTrue(self.client.robot_home()['ok'])
            self.assertTrue(self.engine.armed)

    def test_unconfirmed_stop_cannot_be_bypassed_by_home(self):
        self.engine.uncertain_stop = True
        result = self.client.robot_home()
        self.assertFalse(result['ok'])
        self.assertEqual(self.backends, [])

    def test_legacy_home_does_not_forge_empty_gripper_confirmation(self):
        self.client.robot_home = lambda: self.client._call('home', {})
        result = self.client.robot_home()
        self.assertFalse(result['ok'])

    def test_new_stop_during_home_still_cancels(self):
        self.block = True
        results = []
        thread = threading.Thread(target=lambda: results.append(self.client.robot_home()))
        thread.start()
        try:
            self.assertTrue(self.entered.wait(1))
            self.assertTrue(self.client.robot_stop()['ok'])
        finally:
            self.release.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertFalse(results[0]['ok'])
        self.assertFalse(self.engine.armed)


if __name__ == '__main__':
    unittest.main()
