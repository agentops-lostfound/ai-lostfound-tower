import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from robot.phone_carry import augmented_poses, execution_plan, load_config
from robot.studio_extension.runtime.saved_pose import PoseMove, SavedPoseMixin
from tests.sequence_fixtures import expected_sequence, taught_poses


class PhoneCarryTests(unittest.TestCase):
    def test_only_approved_routes_use_compensation_and_unload_after_open(self):
        original = taught_poses()
        before = copy.deepcopy(original)
        for n in range(1, 9):
            sequence = expected_sequence(n)
            commands, poses, profiles = execution_plan(sequence, original)
            changed = [i for i, (a, b) in enumerate(zip(sequence, commands)) if a != b]
            self.assertEqual(changed, [5, 6, 7, 8] if n in (1, 2, 3, 7) else [])
            for i in changed:
                for key in original[sequence[i]]:
                    self.assertEqual(poses[commands[i]][key], original[sequence[i]][key]
                                     + (-2 if key == 'shoulder_lift.pos' else 0))
                self.assertEqual(profiles[commands[i]]['reference_pose'], sequence[i])
            self.assertEqual(commands[9:], sequence[9:])
        self.assertEqual(original, before)

    def test_release_keeps_arm_at_loaded_close_then_removes_compensation(self):
        commands, poses, _ = execution_plan(expected_sequence(1), taught_poses())
        for key in poses['close']:
            if key != 'gripper.pos':
                self.assertEqual(poses[commands[7]][key], poses[commands[8]][key])
        self.assertEqual(commands[9], 'outlet_return_1')
        self.assertEqual(commands[10], 'home')

    def test_seven_keeps_special_grip_and_eight_remains_uncompensated(self):
        original = taught_poses()
        commands, poses, _ = execution_plan(expected_sequence(7), original)
        self.assertEqual(commands[5:9], ['pose_7_return_phone', 'outlet_return_1_78_phone',
                                        'close_78_phone', 'open_phone'])
        grip = original['pose_7_close']['gripper.pos']
        for index in (4, 5, 6, 7):
            self.assertEqual(poses[commands[index]]['gripper.pos'], grip)
        for joint in original['close_78']:
            if joint != 'gripper.pos':
                self.assertEqual(poses[commands[7]][joint], poses[commands[8]][joint])
        self.assertEqual(commands[9], 'outlet_return_1_78')
        self.assertEqual(execution_plan(expected_sequence(8), original)[0], expected_sequence(8))

    def test_unsafe_configuration_collision_and_joint_limit_are_rejected(self):
        config = load_config()
        for key, value in [('shoulder_offset_normalized', -4), ('shoulder_offset_normalized', 1),
                           ('shoulder_offset_normalized', float('nan')),
                           ('shoulder_arrival_tolerance_normalized', 9),
                           ('shoulder_arrival_tolerance_normalized', True)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                augmented_poses(taught_poses(), {**config, key: value})
        poses = taught_poses()
        poses['pose_1']['shoulder_lift.pos'] = -99
        with self.assertRaises(ValueError):
            augmented_poses(poses)
        poses = taught_poses()
        poses['pose_1_phone'] = dict(poses['pose_1'])
        with self.assertRaises(ValueError):
            augmented_poses(poses)

    def test_disabled_configuration_leaves_originals_without_aliases(self):
        config = {**load_config(), 'enabled': False}
        poses = taught_poses()
        values, profiles = augmented_poses(poses, config)
        self.assertEqual(values, poses)
        self.assertEqual(profiles, {})

    def test_config_rejects_other_slots(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({**load_config(), 'slots': ['R2-1']}), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_config(path)

    def test_loaded_arrival_uses_original_reference_and_bounded_fixed_command(self):
        reference = np.array([0., 29.09, 0, 0, 0, 4])
        command_target = reference.copy()
        command_target[1] -= 2
        move = PoseMove(reference, command_target, 100., 'owner', 3,
                        arrival_target=reference, shoulder_tolerance=8)
        measured = reference.copy()
        for tick in range(1, 45):
            now = 100 + tick * .1
            move.heartbeat('owner', now)
            command, done = move.tick(measured, now)
            measured = command.copy()
            measured[1] += 7.71  # Repeatable loaded servo error relative to command.
            measured[5] = 43.9  # Phone prevents full closure; never an arrival error.
        self.assertTrue(done)
        self.assertAlmostEqual(float(command[1]), 27.09, places=4)
        self.assertAlmostEqual(float(measured[1]), 34.80, places=4)
        self.assertAlmostEqual(float(move.arrival_target[1]), 29.09, places=4)

    def test_other_arm_joints_still_require_five_and_tracking_limit_stays_ten(self):
        for joint in (0, 2, 3, 4):
            move = PoseMove(np.zeros(6), np.zeros(6), 100, 'owner', shoulder_tolerance=8)
            measured = np.zeros(6)
            measured[joint] = 5.1
            for tick in range(1, 10):
                _, done = move.tick(measured, 100 + tick * .1)
                self.assertFalse(done)
        move = PoseMove(np.zeros(6), np.zeros(6), 100, 'owner', shoulder_tolerance=8)
        measured = np.array([0., 10.1, 0, 0, 0, 0])
        with self.assertRaisesRegex(ValueError, 'following error'):
            move.tick(measured, 100.1)

    def test_invalid_reference_cannot_widen_other_axes_or_change_gripper(self):
        for index in (0, 2, 3, 4, 5):
            target = np.zeros(6)
            target[index] = -2
            with self.assertRaises(ValueError):
                PoseMove(np.zeros(6), target, 100, 'owner', arrival_target=np.zeros(6), shoulder_tolerance=8)
        for tolerance in (9, 4, float('nan'), True):
            with self.assertRaises(ValueError):
                PoseMove(np.zeros(6), np.zeros(6), 100, 'owner', shoulder_tolerance=tolerance)

    def test_runtime_loads_profiles_and_rejects_tampered_pose_file_as_a_whole(self):
        poses, profiles = augmented_poses(taught_poses())
        data = {'follower_id': 'test', 'poses': poses, 'motion_profiles': profiles}
        source = SavedPoseMixin()
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            source._init_saved_poses()
        self.assertIsNone(source._pose_error)
        self.assertEqual(set(source._saved_pose_state()['saved_pose_profile_names']), set(profiles))
        data['poses']['close_phone']['wrist_flex.pos'] += 2
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            source._init_saved_poses()
        self.assertTrue(source._pose_error)
        self.assertEqual(source._saved_poses, {})
