import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from robot.command_correction import load_command_corrections
from robot.studio_extension.runtime.saved_pose import JOINTS, KEYS, PoseMove, SavedPoseMixin


class FixedCommandCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.reference = np.array([26.65, 7.54, 18.72, 42.38, -18.24, 57.36])
        self.bias = np.array([.51, 1.68, -.09, .60, -.20, 0.])
        self.offset = -self.bias[:5]
        self.profile = {'reference': dict(zip(KEYS, self.reference)),
                        'offsets': dict(zip(KEYS[:5], self.offset)), 'arrival_tolerance': .5}

    def test_fixed_inverse_command_reaches_taught_measurement_without_dynamic_changes(self):
        target = self.reference.copy()
        target[:5] += self.offset
        move = PoseMove(np.zeros(6), target, 100., 'test', arrival_target=self.reference,
                        arm_command_offsets=self.offset, arrival_tolerance=.5)
        measured = np.zeros(6)
        for tick in range(1, 150):
            now = 100 + tick / 30
            move.heartbeat('test', now)
            command, done = move.tick(measured, now)
            measured = command + self.bias
            if move.command_complete:
                np.testing.assert_allclose(command, target, atol=2e-6)
            if done:
                break
        self.assertTrue(done)
        np.testing.assert_allclose(measured, self.reference, atol=2e-6)
        np.testing.assert_array_equal(move.arrival_target, self.reference)
        self.assertAlmostEqual(command[5], self.reference[5], places=4)

    def test_wrong_response_is_not_declared_arrived_and_never_changes_fixed_endpoint(self):
        target = self.reference.copy(); target[:5] += self.offset
        move = PoseMove(target, target, 100., 'test', arrival_target=self.reference,
                        arm_command_offsets=self.offset, arrival_tolerance=.5)
        for tick in range(1, 90):
            move.heartbeat('test', 100 + tick / 30)
            command, done = move.tick(target, 100 + tick / 30)
            self.assertFalse(done)
            np.testing.assert_allclose(command, target, atol=2e-6)

    def test_original_five_unit_margin_can_be_restored_without_changing_offset(self):
        target = self.reference.copy(); target[:5] += self.offset
        move = PoseMove(target, target, 100., 'test', arrival_target=self.reference,
                        arm_command_offsets=self.offset, arrival_tolerance=5.)
        np.testing.assert_array_equal(move.arrival_tolerances, [5., 7., 8., 5., 5.])
        for tick in range(1, 20):
            now = 100 + tick / 30
            move.heartbeat('test', now)
            command, done = move.tick(target, now)
        self.assertTrue(done)
        np.testing.assert_allclose(command, target, atol=2e-6)
        with self.assertRaises(ValueError):
            PoseMove(target, target, 100., 'test', arrival_target=self.reference,
                     arm_command_offsets=self.offset, arrival_tolerance=5.01)

    def test_invalid_dimensions_gripper_change_and_excess_offset_are_rejected(self):
        for offsets in ([0.] * 4, [0.] * 6, [0, 3.01, 0, 0, 0], [0, float('nan'), 0, 0, 0]):
            with self.subTest(offsets=offsets), self.assertRaises(ValueError):
                PoseMove(self.reference, self.reference, 100., 'test',
                         arm_command_offsets=offsets, arrival_tolerance=.5)
        target = self.reference.copy(); target[:5] += self.offset; target[5] += 1
        with self.assertRaises(ValueError):
            PoseMove(self.reference, target, 100., 'test', arrival_target=self.reference,
                     arm_command_offsets=self.offset, arrival_tolerance=.5)

    def test_runtime_exposes_correction_and_rejects_different_teaching(self):
        data = {'follower_id': 'test', 'poses': {'pose_7_target': self.profile['reference']},
                'command_corrections': {'pose_7_target': self.profile}}
        source = SavedPoseMixin()
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            source._init_saved_poses()
        self.assertIsNone(source._pose_error)
        self.assertEqual(source._saved_pose_state()['saved_pose_command_corrections'], data['command_corrections'])
        data['poses']['pose_7_target'] = {**data['poses']['pose_7_target'], 'wrist_flex.pos': 30.}
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            source._init_saved_poses()
        self.assertIsNotNone(source._pose_error)
        self.assertEqual(source._saved_poses, {})

    def test_reteaching_invalidates_old_correction_and_does_not_modify_poses(self):
        poses = {'pose_7_target': dict(self.profile['reference'])}
        before = copy.deepcopy(poses)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'corrections.json'
            path.write_text(json.dumps({'schema': 'pose_command_corrections.v1',
                                       'poses': {'pose_7_target': self.profile}}), encoding='utf-8')
            self.assertIn('pose_7_target', load_command_corrections(poses, path))
            self.assertEqual(poses, before)
            poses['pose_7_target']['wrist_flex.pos'] += 1
            self.assertEqual(load_command_corrections(poses, path), {})

    def test_runtime_changes_command_only_and_keeps_original_arrival_reference(self):
        data = {'follower_id': 'test', 'poses': {'pose_7_target': self.profile['reference']},
                'command_corrections': {'pose_7_target': self.profile}}
        source = SavedPoseMixin()
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            source._init_saved_poses()
        source._recording = None
        source._follower_source = 'hold'
        source._arming = False
        source._follower = SimpleNamespace(joint_names=JOINTS)
        source._pose_observed_at = time.monotonic()
        source._emit_state = lambda: None
        source._handle_saved_pose(SimpleNamespace(command='move_saved_pose', approved=True,
            follower_id='test', return_to_approach=False, pose='pose_7_target', include_gripper=True,
            token='test', duration_seconds=3), SimpleNamespace(joint_positions=np.zeros(6)))
        expected = self.reference.copy(); expected[:5] += self.offset
        np.testing.assert_allclose(source._pose_move.target, expected)
        np.testing.assert_array_equal(source._pose_move.arrival_target, self.reference)
        np.testing.assert_array_equal(source._saved_poses['pose_7_target'], self.reference)
