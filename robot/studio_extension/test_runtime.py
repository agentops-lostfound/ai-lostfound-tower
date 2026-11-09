"""Run against the staged overlay inside Studio's Python environment. No hardware."""
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


def load_overlay(path):
    import runtime
    import runtime.callbacks
    runtime.__path__.insert(0, str(Path(path) / "runtime"))
    runtime.callbacks.__path__.insert(0, str(Path(path) / "runtime/callbacks"))
    for name in ("runtime.contract", "runtime.saved_pose", "runtime.action_source"):
        sys.modules.pop(name, None)
    return importlib.import_module("runtime.action_source")


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        from runtime.contract import InMemoryCommandMailbox, QueueEventSink
        from runtime.saved_pose import JOINTS
        self.clock = patch("time.monotonic", return_value=100.0)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.box = InMemoryCommandMailbox()
        self.events = QueueEventSink()
        self.robot = SimpleNamespace(joint_names=list(JOINTS))
        self.source = module.StudioActionSource(follower=self.robot, leader=None,
            mailbox=self.box, event_sink=self.events, fps=30, models_dir=Path(tempfile.gettempdir()))
        self.recording = SimpleNamespace(is_recording=False, dataset_loaded=True, episodes_recorded=0, start=Mock(return_value=True))
        self.source.bind_recording(self.recording)
        self.source._saved_poses = {"pose_1": np.array([1., 0, 0, 0, 0, 80]), "home": np.zeros(6), "open": np.array([0.,0,0,0,0,77])}
        self.source._pose_robot_id = "test-follower"
        self.current = np.array([0., 0, 0, 0, 0, 4])
        self.step()

    def step(self, seconds=0.1, follow=True):
        self.now.return_value += seconds
        result = self.source.update(SimpleNamespace(joint_positions=self.current.copy(), timestamp=self.now.return_value), {}, 0)
        if follow:
            self.current = result.copy()
        return result

    def send(self, command, **kwargs):
        from runtime.contract import CommandAdapter
        self.box.apply(CommandAdapter.validate_python(dict(command=command, **kwargs)))

    def move(self, **kwargs):
        args = dict(pose="pose_1", follower_id="test-follower", approved=True, token="owner")
        args.update(kwargs)
        self.send("move_saved_pose", **args)
        return self.step()

    def test_same_source_reaches_all_six_saved_joint_targets(self):
        self.source._pose_last_output[5] = 2
        self.current[5] = 10
        self.move()
        for _ in range(40):
            self.send("saved_pose_heartbeat", token="owner")
            previous = self.current.copy()
            result = self.step()
            self.assertLessEqual(float(np.max(abs(result[:5] - previous[:5]))), 0.061)
        self.assertEqual(result[5], 80)
        self.assertEqual(self.source._pose_status, "arrived")
        self.assertEqual(self.source._approach_pose, "pose_1")
        self.assertEqual(self.source.follower_source, "hold")
        self.assertIs(self.source._follower, self.robot)

    def test_client_loss_stops_without_releasing_grip(self):
        self.move()
        self.step(1.1)
        self.assertEqual(self.source._pose_status, "error")
        self.assertIsNone(self.source._pose_move)
        self.assertEqual(self.source._hold_target[5], 4)

    def test_live_leader_positions_are_in_observation_events(self):
        from runtime.callbacks.stream import StreamCallback
        from runtime.transport.codec import decode_event, encode_event
        self.source._leader_reads_enabled = True
        self.source._last_leader_action = np.array([1., 2, 3, 4, 5, 6])
        self.source._last_leader_timestamp = self.now.return_value
        events = Mock()
        callback = StreamCallback(event_sink=events, follower_source=lambda: "hold",
            leader_positions=self.source.leader_positions)
        callback._joint_names = self.robot.joint_names
        callback.on_tick(SimpleNamespace(action_sent=self.current,
            robot_state=SimpleNamespace(joint_positions=self.current)))
        event = events.emit.call_args.args[0]
        decoded, _, _ = decode_event(encode_event(event))
        self.assertEqual(decoded.leader['gripper.pos'], 6)
        self.assertEqual(decoded.leader['elbow_flex.pos'], 3)
        self.assertEqual(decoded.data['elbow_flex.pos'], 0)

    def test_stale_or_failed_leader_positions_are_not_advertised(self):
        self.source._leader_reads_enabled = True
        self.source._last_leader_action = np.zeros(6)
        self.source._last_leader_timestamp = self.now.return_value
        self.assertIsNotNone(self.source.leader_positions())
        self.source._leader_failures = 1
        self.assertIsNone(self.source.leader_positions())
        self.source._leader_failures = 0
        self.now.return_value += .6
        self.assertIsNone(self.source.leader_positions())

    def test_wrong_heartbeat_cannot_extend_move(self):
        self.move()
        self.send("saved_pose_heartbeat", token="another-tab")
        self.step(1.1)
        self.assertEqual(self.source._pose_status, "error")

    def test_recording_blocks_pose(self):
        self.recording.is_recording = True
        self.move()
        self.assertIsNone(self.source._pose_move)

    def test_move_blocks_teleop_policy_recording_and_legacy_panel(self):
        self.move()
        for command, extra in [("start_task", {"task":"grasp"}), ("start_recording", {"task":"grasp"}),
                ("set_follower_source", {"follower_source":"teleop"})]:
            self.send(command, **extra)
            self.step()
            self.assertEqual(self.source.follower_source, "hold")
            self.assertIsNotNone(self.source._pose_move)
        self.recording.start.assert_not_called()

    def hold_unconfirmed_target(self):
        self.move()
        self.current[0] = -2
        for _ in range(33):
            self.send("saved_pose_heartbeat", token="owner")
            self.step(follow=False)
        self.assertEqual(self.source._pose_status, "holding_target")

    def test_unconfirmed_target_holds_and_allows_next_saved_pose(self):
        self.hold_unconfirmed_target()
        for _ in range(20):
            self.step(follow=False)
        self.assertEqual(self.source._pose_status, "holding_target")
        self.assertIsNone(self.source._approach_pose)
        self.move(pose="home")
        self.assertEqual(self.source._pose_status, "moving")
        self.assertEqual(self.source._pose_name, "home")
        np.testing.assert_array_equal(self.source._pose_move.target, self.source._saved_poses['home'])

    def test_teleop_replaces_unconfirmed_target_monitoring(self):
        self.hold_unconfirmed_target()
        self.source._leader_reads_enabled = True
        self.source._last_leader_action = self.current.copy()
        self.source._last_leader_timestamp = self.now.return_value
        self.source._leader = Mock()
        self.source._leader.get_observation.return_value = SimpleNamespace(
            joint_positions=self.current.copy(), timestamp=self.now.return_value + .1)
        self.send("set_follower_source", follower_source="teleop")
        self.step(follow=False)
        self.assertEqual(self.source.follower_source, "teleop")
        self.assertIsNone(self.source._pose_move)

    def test_unconfirmed_target_still_blocks_recording(self):
        self.hold_unconfirmed_target()
        self.send("start_recording", task="grasp")
        self.step(follow=False)
        self.recording.start.assert_not_called()

    def test_stop_cancels_no_later_resume(self):
        self.move()
        self.send("stop_saved_pose")
        result = self.step()
        self.assertEqual(self.source._pose_status, "stopped")
        for _ in range(5):
            np.testing.assert_array_equal(self.step(), result)

    def test_return_requires_successful_approach(self):
        self.move(return_to_approach=True)
        self.assertIsNone(self.source._pose_move)
        self.assertIn("approach", self.source._pose_error)

    def test_return_uses_pinned_approach_not_new_selection(self):
        self.source._approach_pose = "pose_1"
        self.move(pose="home", return_to_approach=True)
        self.assertEqual(self.source._pose_name, "pose_1")
        np.testing.assert_array_equal(self.source._pose_move.target, self.source._saved_poses['pose_1'])

    def test_follower_binding_and_approval(self):
        self.move(follower_id="other")
        self.assertIsNone(self.source._pose_move)
        self.move(approved=False)
        self.assertIsNone(self.source._pose_move)

    def test_selected_duration_is_used_by_the_runtime(self):
        self.move(duration_seconds=5)
        self.assertEqual(self.source._pose_move.duration_seconds, 5)

    def test_invalid_duration_is_rejected_before_motion(self):
        for duration in (2, 6, -1, 4.5):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                self.move(duration_seconds=duration)
        self.assertIsNone(self.source._pose_move)

    def test_saving_blocks_motion_and_new_recording(self):
        self.source._pose_episode_finalizing = True
        self.move()
        self.assertIsNone(self.source._pose_move)
        self.send("start_recording", task="grasp")
        self.step()
        self.recording.start.assert_not_called()

    def test_partial_approach_cannot_be_used_for_another_episode(self):
        self.source._approach_pose = "pose_1"
        self.move(pose="home")
        self.send("stop_saved_pose")
        self.step()
        self.assertIsNone(self.source._approach_pose)
        self.source._follower_source = "teleop"
        self.send("start_recording", task="grasp")
        self.step()
        self.recording.start.assert_not_called()

    def test_explicit_legacy_gripper_opt_out_is_supported(self):
        self.move(include_gripper=True)
        self.assertEqual(self.source._pose_move.target[5], 80)
        self.send("stop_saved_pose")
        self.step()
        self.move(pose="open", include_gripper=False)
        self.assertEqual(self.source._pose_move.target[5], 4)
        self.send("stop_saved_pose")
        self.step()
        self.move(pose="open", include_gripper=True)
        self.assertEqual(self.source._pose_move.target[5], 77)

    def test_measured_arrival_not_just_target_ack(self):
        self.move()
        self.current[:5] = [-2,0,0,0,0]
        for _ in range(10):
            self.send("saved_pose_heartbeat", token="owner")
            self.step(follow=False)
        self.assertEqual(self.source._pose_status, "moving")

    def test_tracking_error_and_stale_observation_stop(self):
        self.move()
        self.current[0] = -11
        self.step()
        self.assertEqual(self.source._pose_status, "error")
        self.current = np.zeros(6)
        self.move()
        stamp = self.source._pose_last_timestamp
        self.now.return_value += .6
        self.source.update(SimpleNamespace(joint_positions=self.current, timestamp=stamp), {}, 0)
        self.assertEqual(self.source._pose_status, "error")

    def test_policy_handoff_keeps_robot_and_gripper_command(self):
        policy = Mock()
        policy.update.return_value = np.array([0.,0,0,0,0,2])
        self.source._policy = policy
        self.source._follower_source = "policy"
        self.step()
        self.current[5] = 10
        self.send("set_follower_source", follower_source="hold")
        self.step()
        self.assertEqual(self.source._hold_target[5], 2)
        self.move()
        self.assertIsNotNone(self.source._pose_move)
        policy.disconnect.assert_not_called()

    def test_teleop_alignment_required(self):
        self.source._leader = Mock()
        self.source._leader_reads_enabled = False
        self.source._last_leader_action = np.full(6, 50)
        self.source._last_leader_timestamp = 100
        self.send("set_follower_source", follower_source="teleop")
        self.step()
        self.assertEqual(self.source.follower_source, "hold")

    def test_three_episode_saves_keep_same_runtime_and_devices(self):
        from runtime.session import RuntimeSession
        session = RuntimeSession({}, event_sink=self.events)
        session._action_source = self.source
        session._follower = self.robot
        self.source.bind_recording(session._recording)
        mutation = Mock()
        mutation.save_episode.side_effect = lambda: self.assertTrue(self.source._pose_episode_finalizing)
        session._recording.attach_mutation(mutation)
        for number in range(3):
            session._recording.start("grasp and lift")
            session._save_episode()
            self.assertFalse(session._recording.is_recording)
            self.assertEqual(session._recording.episodes_recorded, number + 1)
            self.assertIs(session._action_source, self.source)
            self.assertIs(session._follower, self.robot)
            self.assertFalse(session._disconnect_requested)
            self.assertFalse(self.source._pose_episode_finalizing)

    def test_recording_callback_excludes_saved_pose_return(self):
        from runtime.callbacks.recording import RecordingCallback
        recording = Mock()
        callback = RecordingCallback(recording=recording, follower_source=lambda: self.source.follower_source)
        callback._joint_names = self.robot.joint_names
        tick = SimpleNamespace(action_sent=self.current, robot_state=SimpleNamespace(joint_positions=self.current), camera_frames={})
        self.source._follower_source = "teleop"
        callback.on_tick(tick)
        self.assertEqual(recording.add_frame.call_count, 1)
        self.source._follower_source = "hold"
        self.move()
        callback.on_tick(tick)
        self.assertEqual(recording.add_frame.call_count, 1)


if __name__ == "__main__":
    import numpy as np
    overlay = sys.argv.pop(1)
    module = load_overlay(overlay)
    unittest.main(verbosity=2)
