import unittest
from collections import deque

import numpy as np

from robot.studio_extension.runtime.saved_pose import PoseMove


class StudioSavedPoseTimingTests(unittest.TestCase):
    def test_selected_profiles_reach_target_command_and_confirm_arrival(self):
        for duration in (3, 4, 5):
            for distance in (0.0, 1.0, 50.0, 200.0):
                with self.subTest(duration=duration, distance=distance):
                    start = np.array([-100.0, 0, 0, 0, 0, 4])
                    target = start.copy()
                    target[0] += distance
                    move = PoseMove(start, target, 100.0, "test", duration)
                    measured = start.copy()
                    for tick in range(1, int((duration + .6) * 30) + 1):
                        now = 100.0 + tick / 30
                        move.heartbeat("test", now)
                        measured, done = move.tick(measured, now)
                        self.assertGreaterEqual(measured[0], start[0])
                        self.assertLessEqual(measured[0], target[0])
                        self.assertEqual(measured[5], 4)
                        if tick == duration * 15:
                            self.assertAlmostEqual(float(measured[0]), start[0] + distance / 2, places=3)
                        if tick == duration * 30:
                            np.testing.assert_allclose(measured, target)
                        if done:
                            break
                    self.assertTrue(done)
                    self.assertLessEqual(now - 100.0, duration + .6)
                    np.testing.assert_allclose(measured, target)

    def test_goal_is_held_past_three_seconds_until_actual_arrival(self):
        start = np.zeros(6)
        target = np.array([10.0, 0, 0, 0, 0, 0])
        move = PoseMove(start, target, 100.0, "test")
        measured = start.copy()
        for tick in range(1, 81):
            now = 100.0 + tick / 10
            move.heartbeat("test", now)
            command, done = move.tick(measured, now)
            measured[0] = max(0.0, command[0] - 6.0)
            self.assertFalse(done)
        np.testing.assert_allclose(command, target)
        for tick in range(81, 86):
            now = 100.0 + tick / 10
            move.heartbeat("test", now)
            command, done = move.tick(target, now)
        self.assertTrue(done)
        np.testing.assert_allclose(command, target)

    def test_delayed_tick_does_not_jump_to_wall_clock_target(self):
        move = PoseMove(np.zeros(6), np.array([100.0, 0, 0, 0, 0, 0]), 100.0, "test")
        move.heartbeat("test", 100.4)
        command, done = move.tick(np.zeros(6), 100.4)
        self.assertLess(command[0], 0.5)
        self.assertFalse(done)

    def test_responding_arm_with_transport_lag_confirms_after_profile_end(self):
        start = np.array([-100.0, 0, 0, 0, 0, 4])
        target = np.array([100.0, 0, 0, 0, 0, 4])
        move = PoseMove(start, target, 100.0, "test")
        measured = start.copy()
        delayed_commands = deque([start.copy() for _ in range(4)])
        peak_instant_error = 0.0
        for tick in range(1, 121):
            now = 100.0 + tick / 30
            move.heartbeat("test", now)
            peak_instant_error = max(peak_instant_error, float(abs(move.command[0] - measured[0])))
            command, done = move.tick(measured, now)
            if done:
                break
            delayed_commands.append(command)
            measured = delayed_commands.popleft()
        self.assertGreater(peak_instant_error, 5.0)
        self.assertTrue(done)
        self.assertLessEqual(now - 100.0, 3.6)

    def test_invalid_profile_durations_are_rejected(self):
        for duration in (0, 2, 6, float('nan'), float('inf')):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                PoseMove(np.zeros(6), np.zeros(6), 100.0, "test", duration)

    def test_completed_command_keeps_target_without_motion_heartbeat(self):
        move = PoseMove(np.zeros(6), np.array([10.0, 0, 0, 0, 0, 4]), 100.0, "test")
        measured = np.zeros(6)
        for tick in range(1, 31):
            now = 100.0 + tick / 10
            move.heartbeat("test", now)
            command, _ = move.tick(measured, now)
            measured = command.copy()
            measured[0] -= 6
        self.assertTrue(move.command_complete)
        for tick in range(31, 81):
            command, done = move.tick(measured, 100.0 + tick / 10)
            self.assertFalse(done)
            np.testing.assert_allclose(command, move.target)

    def test_stalled_joint_still_stops_with_tracking_error(self):
        move = PoseMove(np.zeros(6), np.array([100.0, 0, 0, 0, 0, 0]), 100.0, "test")
        with self.assertRaisesRegex(ValueError, "shoulder_pan.*limit 10"):
            for tick in range(1, 31):
                now = 100.0 + tick / 30
                move.heartbeat("test", now)
                move.tick(np.zeros(6), now)

    def test_same_pose_arrival_uses_shoulder_seven_elbow_eight_other_axes_five(self):
        for joint in range(5):
            for error in (-8.01, -8.0, -7.01, -7.0, -5.01, -5.0, 2.26, 3.44, 5.0, 5.01, 7.0, 7.01, 8.0, 8.01):
                with self.subTest(joint=joint, error=error):
                    move = PoseMove(np.zeros(6), np.zeros(6), 100.0, 'test')
                    measured = np.zeros(6)
                    measured[joint] = error
                    measured[5] = 40.0  # Contact opening is not arm arrival.
                    _, done = move.tick(measured, 100.0)
                    self.assertFalse(done)
                    _, done = move.tick(measured, 100.4)
                    self.assertEqual(done, abs(error) <= (8.0 if joint == 2 else 7.0 if joint == 1 else 5.0))

    def test_arrival_settling_restarts_when_one_joint_leaves_margin(self):
        move = PoseMove(np.zeros(6), np.zeros(6), 100.0, 'test')
        measured = np.full(6, 4.0)
        self.assertFalse(move.tick(measured, 100.0)[1])
        measured[4] = 5.01
        self.assertFalse(move.tick(measured, 100.2)[1])
        measured[4] = 4.0
        self.assertFalse(move.tick(measured, 100.4)[1])
        self.assertFalse(move.tick(measured, 100.6)[1])
        self.assertTrue(move.tick(measured, 100.8)[1])

    def test_tracking_limit_allows_ten_and_stops_above_ten(self):
        move = PoseMove(np.zeros(6), np.zeros(6), 100.0, "test")
        measured = np.array([-10.0, 0, 0, 0, 0, 0])
        move.tick(measured, 100.0)
        measured[0] = -10.01
        with self.assertRaisesRegex(ValueError, "limit 10"):
            move.tick(measured, 100.01)


if __name__ == "__main__":
    unittest.main()
