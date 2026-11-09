import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from robot.joint_motion import JOINTS
from robot.tower_part import TowerRobot


class GraspApproachReturnTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'poses.json'
        zero = {name + '.pos': 0.0 for name in JOINTS}
        self.path.write_text(json.dumps({'pose_1': zero, 'pose_8': zero}), encoding='utf-8')
        self.motion = Mock()
        self.motion.stop.return_value = True
        self.policy = Mock(return_value={'ok': True, 'control_released': True})
        self.part = self.make_part()

    def make_part(self):
        return TowerRobot(motion=self.motion, poses_path=self.path, environ={}, grasp_policy=self.policy)

    def approach(self, part=None, pose='pose_1', slot='R1-1'):
        part = part or self.part
        self.assertTrue(part.robot_go_pose(pose, slot)['ok'])
        self.motion.move.reset_mock()

    def test_grasp_completion_returns_to_original_db_approach_once(self):
        self.approach(pose='pose_8', slot='R4-2')
        def grasp(**kwargs):
            self.motion.move.assert_not_called()
            return {'ok': True, 'control_released': True}
        self.policy.side_effect = grasp
        self.assertTrue(self.part.robot_grasp()['ok'])
        self.policy.assert_called_once_with(approach_pose='pose_8', slot_id='R4-2', cancelled=self.part.cancelled)
        self.motion.move.assert_called_once_with('pose_8', 3, self.part.cancelled, include_gripper=False)
        self.assertFalse(self.part.robot_grasp()['ok'])
        self.policy.assert_called_once()
        self.assertFalse(self.part.robot_verify_grasp()['ok'])  # Motion completion is not object verification.
        self.assertFalse(self.part.robot_deliver()['ok'])

    def test_no_policy_or_no_confirmed_approach_does_not_move(self):
        self.assertFalse(self.part.robot_grasp()['ok'])
        self.policy.assert_not_called()
        part = TowerRobot(motion=self.motion, poses_path=self.path, environ={})
        self.approach(part)
        self.assertFalse(part.robot_grasp()['ok'])
        self.motion.move.assert_not_called()

    def test_failed_or_unreleased_policy_never_starts_lift(self):
        for result in (None, True, {'ok': False}, {'ok': True}, {'ok': True, 'control_released': 1}):
            with self.subTest(result=result):
                part = self.make_part()
                self.approach(part)
                self.policy.return_value = result
                self.motion.stop.reset_mock()
                self.assertFalse(part.robot_grasp()['ok'])
                self.motion.move.assert_not_called()
                self.motion.stop.assert_called_once()
                self.assertTrue(part.cancelled.is_set())

    def test_stop_at_policy_completion_prevents_lift(self):
        self.approach()
        def grasp(**kwargs):
            self.part.robot_stop()
            return {'ok': True, 'control_released': True}
        self.policy.side_effect = grasp
        self.assertFalse(self.part.robot_grasp()['ok'])
        self.motion.move.assert_not_called()

    def test_policy_exception_stops_and_does_not_resume(self):
        self.approach()
        self.policy.side_effect = RuntimeError('policy failed')
        self.assertFalse(self.part.robot_grasp()['ok'])
        self.motion.stop.assert_called_once()
        self.motion.move.assert_not_called()
        self.assertFalse(self.part.robot_go_pose('pose_1', 'R1-1')['ok'])

    def test_grasp_does_not_finish_until_approach_arrival(self):
        self.approach()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.motion.move.side_effect = lambda *args, **kwargs: (entered.set(), release.wait(2))
        results = []
        thread = threading.Thread(target=lambda: results.append(self.part.robot_grasp()))
        thread.start()
        self.assertTrue(entered.wait(1))
        self.assertEqual(results, [])
        self.assertFalse(self.part.robot_go_pose('pose_8', 'R4-2')['ok'])
        self.assertFalse(self.part.robot_grasp()['ok'])
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]['ok'])

    def test_lift_failure_stops_and_never_runs_outlet(self):
        self.approach()
        self.motion.move.side_effect = RuntimeError('following error')
        result = self.part.robot_grasp()
        self.assertFalse(result['ok'])
        self.assertIn('following error', result['reason'])
        self.motion.move.assert_called_once_with('pose_1', 3, self.part.cancelled, include_gripper=False)
        self.motion.stop.assert_called_once()

    def test_stop_during_lift_cannot_report_success(self):
        self.approach()
        self.motion.move.side_effect = lambda *args, **kwargs: self.part.robot_stop()
        self.assertFalse(self.part.robot_grasp()['ok'])
        self.assertTrue(self.part.cancelled.is_set())

    def test_failed_new_approach_invalidates_previous_grasp_start(self):
        self.approach()
        self.motion.move.side_effect = RuntimeError('move failed')
        self.assertFalse(self.part.robot_go_pose('pose_8', 'R4-2')['ok'])
        self.assertFalse(self.part.robot_grasp()['ok'])
        self.policy.assert_not_called()

    def test_invalid_new_db_target_cannot_reuse_old_grasp_start(self):
        self.approach()
        self.assertFalse(self.part.robot_go_pose('pose_8', 'R1-1')['ok'])
        self.assertFalse(self.part.robot_grasp()['ok'])
        self.policy.assert_not_called()
        self.motion.move.assert_not_called()
