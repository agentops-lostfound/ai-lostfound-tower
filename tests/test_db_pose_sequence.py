import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from agents.storage import OUTLET_SEQUENCE, SLOT_NUMBERS
from robot.db_pose_sequence import sequence_for_target, simulate_trigger, trigger_db_sequence
from robot.joint_motion import JOINTS
from robot.tower_part import TowerRobot
from tests.sequence_fixtures import taught_poses, expected_sequence


class DbSequenceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'poses.json'
        self.poses = taught_poses()
        self.path.write_text(json.dumps(self.poses), encoding='utf-8')
        self.motion = Mock()
        self.robot = TowerRobot(motion=self.motion, poses_path=self.path, environ={})

    def target(self, slot='R3-2'):
        return {'ok': True, 'item_id': 'A-W31', 'slot_id': slot,
                'pose_name': f'pose_{SLOT_NUMBERS[slot]}', 'number': SLOT_NUMBERS[slot],
                'outlet_sequence': list(OUTLET_SEQUENCE)}

    def test_all_eight_db_slots_build_and_execute_the_exact_sequence(self):
        with patch('subprocess.Popen') as process, patch('urllib.request.urlopen') as network:
            for slot, number in SLOT_NUMBERS.items():
                with self.subTest(slot=slot):
                    result = simulate_trigger(slot, self.path)
                    expected = expected_sequence(number)
                    self.assertTrue(result['ok'])
                    self.assertEqual(result['completed'], expected)
                    self.assertTrue(result['test_only'] and result['vla_skipped'])
                    self.assertEqual(result['hardware_commands'], 0)
                    self.assertEqual(result['final_item_status'], '본센터 보관')
                    self.assertEqual(result['events'][0]['event'], 'db_target_lookup')
                    events = result['events'][1:]
                    commands = list(expected)
                    if number in (1, 2, 3, 7):
                        for index in (5, 6, 7, 8):
                            commands[index] += '_phone'
                    for i, pose in enumerate(expected):
                        self.assertEqual([e['event'] for e in events[i*2:i*2+2]], ['requested', 'arrived'])
                        self.assertEqual([e['pose'] for e in events[i*2:i*2+2]], [commands[i], commands[i]])
                    self.assertEqual(result['command_sequence'], commands)
                    self.assertEqual(result['target']['slot_id'], slot)
                    self.assertEqual(result['target']['number'], number)
            process.assert_not_called()
            network.assert_not_called()

    def test_profile_options_3_4_5_use_same_order_and_wait_for_arrival(self):
        for duration in (3, 4, 5):
            result = simulate_trigger('R3-2', self.path, duration)
            arrivals = [e for e in result['events'] if e['event'] == 'arrived']
            self.assertTrue(result['ok'])
            self.assertEqual(len(arrivals), 11)
            # The initial home is already reached; all subsequent moves use the selected profile.
            self.assertTrue(all(e['elapsed'] >= duration for e in arrivals[1:]))

    def test_trigger_uses_lookup_once_and_rejects_other_item(self):
        lookup = Mock(return_value=self.target())
        result = trigger_db_sequence('A-W31', lookup, self.robot)
        lookup.assert_called_once_with('A-W31')
        self.assertTrue(result['ok'])
        self.motion.move.reset_mock()
        self.assertFalse(trigger_db_sequence('A-W32', lookup, self.robot)['ok'])
        self.motion.move.assert_not_called()

    def test_missing_later_pose_prevents_the_first_motion(self):
        del self.robot.poses['open']
        result = self.robot.run_pose_sequence_test(self.target())
        self.assertFalse(result['ok'])
        self.assertEqual(result['completed'], [])
        self.motion.move.assert_not_called()

    def test_release_must_not_lower_arm_and_special_grip_must_not_change(self):
        self.robot.poses['open']['shoulder_lift.pos'] += 10.0
        self.assertFalse(self.robot.run_pose_sequence_test(self.target())['ok'])
        self.motion.move.assert_not_called()
        self.robot.poses['open']['shoulder_lift.pos'] -= 10.0
        self.robot.poses['pose_8_return']['gripper.pos'] = 4.0
        self.assertFalse(self.robot.run_pose_sequence_test(self.target('R4-2'))['ok'])
        self.motion.move.assert_not_called()

    def test_failure_in_middle_stops_and_does_not_execute_remaining_stages(self):
        self.motion.move.side_effect = [None, RuntimeError('simulated failure')]
        self.motion.stop.return_value = True
        result = self.robot.run_pose_sequence_test(self.target())
        self.assertFalse(result['ok'])
        self.assertEqual(result['completed'], ['home'])
        self.assertEqual(result['failed_pose'], 'pose_6')
        self.assertEqual(self.motion.move.call_count, 2)
        self.motion.stop.assert_called_once()

    def test_cancellation_between_stages_does_not_advance(self):
        self.motion.move.side_effect = lambda *args: self.robot.cancelled.set()
        result = self.robot.run_pose_sequence_test(self.target())
        self.assertFalse(result['ok'])
        self.assertEqual(result['completed'], [])
        self.motion.move.assert_called_once()

    def test_next_pose_is_not_requested_until_first_move_returns(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def move(*args):
            if self.motion.move.call_count == 1:
                entered.set()
                release.wait(2)
        self.motion.move.side_effect = move
        results = []
        thread = threading.Thread(target=lambda: results.append(self.robot.run_pose_sequence_test(self.target())))
        thread.start()
        self.assertTrue(entered.wait(1))
        self.assertEqual(self.motion.move.call_count, 1)
        self.assertFalse(self.robot.robot_go_pose('pose_1', 'R1-1')['ok'])
        release.set()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]['ok'])
        self.assertEqual([c.args[0] for c in self.motion.move.call_args_list], expected_sequence(6))

    def test_ambiguous_db_targets_are_rejected_before_any_motion(self):
        for changes in ({'ok': False}, {'slot_id': 'H-1'}, {'pose_name': 'pose_1'},
                        {'number': 1}, {'number': True}, {'outlet_sequence': ['home']}):
            with self.subTest(changes=changes):
                target = {**self.target(), **changes}
                with self.assertRaises(ValueError):
                    sequence_for_target(target)
                self.assertFalse(self.robot.run_pose_sequence_test(target)['ok'])
        self.motion.move.assert_not_called()

    def test_test_route_never_calls_production_grasp_or_deliver(self):
        with patch.object(self.robot, 'robot_grasp') as grasp, patch.object(self.robot, 'robot_deliver') as deliver:
            self.assertTrue(self.robot.run_pose_sequence_test(self.target())['ok'])
            grasp.assert_not_called()
            deliver.assert_not_called()
        self.assertFalse(self.robot.robot_grasp()['ok'])
        self.assertFalse(self.robot.robot_deliver()['ok'])


if __name__ == '__main__':
    unittest.main()
