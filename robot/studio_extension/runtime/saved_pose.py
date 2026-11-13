"""Saved SO101 poses executed by Studio's existing action source, never serial.

The browser supplies a heartbeat while a move is active. This bounds motion
after client loss; it is not a hardware emergency stop or collision planner.
"""
from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

import numpy as np

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
KEYS = tuple(name + ".pos" for name in JOINTS)
MOVE_DURATION_SECONDS = 3.0
TRACKING_LAG_SECONDS = 0.15
ARM_FOLLOWING_ERROR_LIMIT = 10.0
# Residual motor error is expected even when re-requesting the current pose.
# This is per arm joint in normalized units, independent of the tracking limit.
ARM_ARRIVAL_TOLERANCE = 5.0
ELBOW_ARRIVAL_TOLERANCE = 8.0
SHOULDER_ARRIVAL_TOLERANCE = 7.0
MAX_COMMAND_CORRECTION = 3.0


def checked_command_correction(profile, reference):
    """A measured, fixed arm-command correction tied to one exact teaching."""
    if not np.array_equal(vector(profile['reference']), np.asarray(reference)):
        raise ValueError('Command correction belongs to a different teaching')
    offsets = profile['offsets']
    if set(offsets) != set(KEYS[:5]) or any(type(v) not in (int, float) for v in offsets.values()):
        raise ValueError('Command correction requires exactly five arm offsets')
    values = np.array([offsets[key] for key in KEYS[:5]], dtype=float)
    tolerance = profile['arrival_tolerance']
    if (not np.isfinite(values).all() or np.any(np.abs(values) > MAX_COMMAND_CORRECTION)
            or type(tolerance) not in (int, float) or not .25 <= tolerance <= ARM_ARRIVAL_TOLERANCE):
        raise ValueError('Command correction exceeds its validated bounds')
    corrected = np.asarray(reference).copy()
    corrected[:5] += values
    vector(dict(zip(KEYS, corrected)))
    return values, tolerance


def vector(values):
    if set(values) != set(KEYS):
        raise ValueError("Exactly six named SO101 joints are required")
    result = np.array([values[key] for key in KEYS], dtype=float)
    if not np.isfinite(result).all() or (result[:5] < -100).any() or (result > 100).any() or result[5] < 0:
        raise ValueError("Invalid normalized SO101 joint values")
    return result


class PoseMove:
    """Bounded joint interpolation with measured arrival and a client lease."""

    def __init__(self, start, target, now, token, duration_seconds=MOVE_DURATION_SECONDS,
                 *, arrival_target=None, shoulder_tolerance=ARM_ARRIVAL_TOLERANCE,
                 arm_command_offsets=None, arrival_tolerance=None):
        if duration_seconds not in (3, 4, 5):
            raise ValueError("Movement duration must be 3, 4 or 5 seconds")
        self.duration_seconds = float(duration_seconds)
        self.start = np.array(start, dtype=float, copy=True)
        self.command = self.start.copy()
        self.target = np.array(target, dtype=float, copy=True)
        self.arrival_target = self.target.copy() if arrival_target is None else np.array(arrival_target, dtype=float, copy=True)
        if (self.arrival_target.shape != (6,) or not np.isfinite(self.arrival_target).all()
                or type(shoulder_tolerance) not in (int, float) or not np.isfinite(shoulder_tolerance)
                or not ARM_ARRIVAL_TOLERANCE <= shoulder_tolerance <= 8):
            raise ValueError("Invalid arrival reference or shoulder tolerance")
        delta = self.target - self.arrival_target
        if arm_command_offsets is None:
            if np.any(np.abs(delta[[0, 2, 3, 4, 5]]) > 1e-5) or not -3 <= delta[1] <= 0:
                raise ValueError("Only bounded negative shoulder compensation is allowed")
            if arrival_tolerance is not None:
                raise ValueError('A precision arrival margin requires a measured command correction')
        else:
            arm_command_offsets = np.asarray(arm_command_offsets, dtype=float)
            if arm_command_offsets.shape != (5,):
                raise ValueError('Command correction requires exactly five arm offsets')
            offsets, arrival_tolerance = checked_command_correction({
                'reference': dict(zip(KEYS, self.arrival_target)),
                'offsets': dict(zip(KEYS[:5], map(float, arm_command_offsets))),
                'arrival_tolerance': arrival_tolerance,
            }, self.arrival_target)
            if abs(delta[5]) > 1e-5 or not np.allclose(delta[:5], offsets, atol=1e-5, rtol=0):
                raise ValueError('Command target differs from the measured correction')
        self.arrival_tolerances = np.full(5, ARM_ARRIVAL_TOLERANCE)
        self.arrival_tolerances[1] = shoulder_tolerance
        if arm_command_offsets is not None:
            self.arrival_tolerances[:] = arrival_tolerance
        # Operator-approved elbow margin also applies to corrected teachings.
        self.arrival_tolerances[2] = ELBOW_ARRIVAL_TOLERANCE
        self.arrival_tolerances[1] = max(self.arrival_tolerances[1], SHOULDER_ARRIVAL_TOLERANCE)
        self.command_complete = bool(np.max(np.abs(self.target - self.command)) < 1e-5)
        self.token = token
        self.elapsed = 0.0
        self.last_tick = now
        self.last_heartbeat = now
        self.settled_since = None
        self.command_history = deque([(now, self.command.copy())])

    def heartbeat(self, token, now):
        if token == self.token:
            self.last_heartbeat = now

    def tick(self, measured, now):
        measured = np.asarray(measured, dtype=float)
        if measured.shape != (6,) or not np.isfinite(measured).all():
            raise ValueError("Invalid robot observation")
        if not self.command_complete and now - self.last_heartbeat > 1.0:
            raise ValueError("Control heartbeat lost; move stopped")
        # Compare with the recent command path to allow measured motor/IPC lag.
        # A stationary joint still falls outside this bounded time window.
        cutoff = now - TRACKING_LAG_SECONDS
        while len(self.command_history) > 1 and self.command_history[1][0] <= cutoff:
            self.command_history.popleft()
        past_time, past_command = self.command_history[0]
        if len(self.command_history) > 1:
            next_time, next_command = self.command_history[1]
            fraction = max(0.0, min((cutoff - past_time) / (next_time - past_time), 1.0))
            past_command = past_command + fraction * (next_command - past_command)
        lower = np.minimum(past_command[:5], self.command[:5])
        upper = np.maximum(past_command[:5], self.command[:5])
        errors = np.maximum(lower - measured[:5], measured[:5] - upper)
        joint = int(np.argmax(errors))
        if errors[joint] > ARM_FOLLOWING_ERROR_LIMIT:
            raise ValueError(
                f"Arm following error: {JOINTS[joint]} exceeds the recent command path "
                f"by {errors[joint]:.1f} normalized units (limit {ARM_FOLLOWING_ERROR_LIMIT:g})"
            )
        dt = max(0.0, min(now - self.last_tick, 0.1))
        self.last_tick = now
        self.elapsed += dt
        progress = min(1.0, self.elapsed / self.duration_seconds)
        # Ease both ends while all joints finish together, regardless of distance.
        blend = progress * progress * (3.0 - 2.0 * progress)
        self.command = self.start + (self.target - self.start) * blend
        if now > self.command_history[-1][0]:
            self.command_history.append((now, self.command.copy()))
        self.command_complete = bool(np.max(np.abs(self.target - self.command)) < 1e-5)
        arrived = self.command_complete and np.all(np.abs(self.arrival_target[:5] - measured[:5]) <= self.arrival_tolerances)
        if arrived:
            self.settled_since = now if self.settled_since is None else self.settled_since
        else:
            self.settled_since = None
        done = self.settled_since is not None and now - self.settled_since >= 0.3
        return self.command.astype(np.float32), done


class SavedPoseMixin:
    def _init_saved_poses(self):
        self._pose_move = None
        self._pose_status = "idle"
        self._pose_name = None
        self._approach_pose = None
        self._pose_error = None
        self._pose_last_output = None
        self._pose_last_timestamp = None
        self._pose_observed_at = None
        self._saved_poses = {}
        self._pose_motion_profiles = {}
        self._pose_command_corrections = {}
        self._pose_robot_id = None
        self._pose_episode_finalizing = False
        try:
            data = json.loads(Path(__file__).with_name("saved_poses.json").read_text(encoding="utf-8"))
            self._pose_robot_id = data["follower_id"]
            self._saved_poses = {name: vector(value) for name, value in data["poses"].items()}
            for name, profile in data.get("motion_profiles", {}).items():
                if not name.endswith('_phone') or name not in self._saved_poses:
                    raise ValueError("Invalid compensated pose name")
                reference = self._saved_poses[profile['reference_pose']]
                offset = profile['shoulder_offset']
                if type(offset) not in (int, float) or not np.isfinite(offset) or not -3 <= offset <= 0:
                    raise ValueError("Invalid fixed shoulder offset")
                checked = PoseMove(reference, self._saved_poses[name], 0., 'validate',
                                   arrival_target=reference, shoulder_tolerance=profile['shoulder_tolerance'])
                if abs(checked.target[1] - reference[1] - profile['shoulder_offset']) > 1e-5:
                    raise ValueError("Compensated shoulder differs from profile")
                self._pose_motion_profiles[name] = profile
            for name, profile in data.get('command_corrections', {}).items():
                if name not in self._saved_poses or name in self._pose_motion_profiles:
                    raise ValueError('Command correction requires an ordinary saved teaching')
                checked_command_correction(profile, self._saved_poses[name])
                self._pose_command_corrections[name] = profile
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._saved_poses = {}
            self._pose_motion_profiles = {}
            self._pose_command_corrections = {}
            self._pose_error = "Saved poses unavailable: " + str(exc)

    def _saved_pose_state(self):
        return dict(saved_pose_status=self._pose_status, saved_pose_name=self._pose_name,
                    saved_pose_error=self._pose_error, saved_pose_names=list(self._saved_poses),
                    saved_pose_robot_id=self._pose_robot_id, approach_pose=self._approach_pose,
                    saved_pose_token=self._pose_move.token if self._pose_move else None,
                    saved_pose_profile_names=list(self._pose_motion_profiles),
                    saved_pose_motion_profiles=dict(self._pose_motion_profiles),
                    saved_pose_command_corrections=dict(self._pose_command_corrections))

    def leader_positions(self):
        if (not self._leader_reads_enabled or self._leader_failures or self._last_leader_action is None
                or self._last_leader_timestamp is None or time.monotonic() - self._last_leader_timestamp > 0.5):
            return None
        return dict(zip(KEYS, map(float, self._last_leader_action)))

    def _pose_fail(self, message):
        from runtime.contract import ErrorEvent
        self._pose_error = message
        self._event_sink.emit(ErrorEvent(message=message, error_code="saved_pose_rejected"))
        self._emit_state()

    def _pose_hold(self, robot_state):
        held = np.array(robot_state.joint_positions, dtype=np.float32, copy=True)
        previous = self._pose_last_output
        if previous is not None:
            held[5] = previous[5]
        self._cancel_arming()
        self._follower_source = "hold"
        self._hold_target = held

    def _cancel_saved_pose(self, robot_state, reason="stopped"):
        self._pose_hold(robot_state)
        self._pose_move = None
        self._pose_status = reason
        self._emit_state()

    def _handle_saved_pose(self, command, robot_state):
        now = time.monotonic()
        if command.command == "saved_pose_heartbeat":
            if self._pose_move:
                self._pose_move.heartbeat(command.token, now)
            return
        if command.command == "stop_saved_pose":
            self._cancel_saved_pose(robot_state)
            return
        try:
            if not command.approved:
                raise ValueError("Confirm the movement path before moving")
            if self._pose_move is not None and self._pose_status == "moving":
                raise ValueError("A pose move is already active")
            if self._recording is not None and self._recording.is_recording:
                raise ValueError("Save or discard the episode before moving")
            if self._pose_episode_finalizing:
                raise ValueError("Wait for episode saving to finish")
            if getattr(self, "_manual_stop_latched", False):
                raise ValueError("Manual stop is latched; repair required")
            if self._follower_source != "hold" or self._arming:
                raise ValueError("Switch to hold before moving")
            if list(self._follower.joint_names) != list(JOINTS):
                raise ValueError("Saved poses require the calibrated SO101 joint ordering")
            if command.follower_id != self._pose_robot_id:
                raise ValueError("Pose file belongs to a different follower")
            if self._pose_observed_at is None or now - self._pose_observed_at > 0.5:
                raise ValueError("Fresh robot observations required")
            name = self._approach_pose if command.return_to_approach else command.pose
            if name not in self._saved_poses:
                raise ValueError("Select and reach an approach pose first" if command.return_to_approach else "Unknown pose")
            start = vector(dict(zip(KEYS, robot_state.joint_positions)))
            if self._pose_last_output is not None:
                start[5] = self._pose_last_output[5]
            target = self._saved_poses[name].copy()
            correction = self._pose_command_corrections.get(name)
            options = {}
            if correction:
                offsets, tolerance = checked_command_correction(correction, target)
                target[:5] += offsets
                options = {'arm_command_offsets': offsets, 'arrival_tolerance': tolerance}
            if not command.include_gripper:
                target[5] = start[5]
            profile = self._pose_motion_profiles.get(name)
            if name.endswith('_phone') and profile is None:
                raise ValueError("Phone carry arrival profile is missing")
            arrival = self._saved_poses[profile['reference_pose']].copy() if profile else self._saved_poses[name].copy()
            if not command.include_gripper:
                arrival[5] = start[5]
            self._pose_move = PoseMove(start, target, now, command.token, command.duration_seconds,
                arrival_target=arrival, shoulder_tolerance=profile['shoulder_tolerance'] if profile else ARM_ARRIVAL_TOLERANCE,
                **options)
            self._approach_pose = None
            self._pose_name = name
            self._pose_status = "moving"
            self._pose_error = None
            self._emit_state()
        except (ValueError, TypeError) as exc:
            self._pose_fail(str(exc))

    def _tick_saved_pose(self, robot_state):
        move = self._pose_move
        if move is None:
            return
        try:
            now = time.monotonic()
            if self._pose_observed_at is None or now - self._pose_observed_at > 0.5:
                raise ValueError("Robot observation stopped advancing")
            self._hold_target, done = move.tick(robot_state.joint_positions, now)
            if done:
                self._pose_move = None
                self._pose_status = "arrived"
                if self._pose_name in {f"pose_{i}" for i in range(1, 9)}:
                    self._approach_pose = self._pose_name
                self._emit_state()
            elif move.command_complete and self._pose_status == "moving":
                self._pose_status = "holding_target"
                self._emit_state()
        except ValueError as exc:
            self._cancel_saved_pose(robot_state, "error")
            self._pose_fail(str(exc))

    def _observe_saved_pose(self, robot_state):
        stamp = robot_state.timestamp
        if self._pose_last_timestamp is None or stamp > self._pose_last_timestamp:
            self._pose_last_timestamp = stamp
            self._pose_observed_at = time.monotonic()

    def _remember_pose_output(self, values):
        self._pose_last_output = np.array(values, dtype=np.float32, copy=True)
        return values

    def _pose_command_blocked(self, command, robot_state):
        """Backend exclusion also protects against a second browser/client."""
        if command.command in {"stop_task", "manual_joint_control"} or (
            command.command == "set_follower_source" and command.follower_source == "hold"
        ):
            self._cancel_saved_pose(robot_state)
            return command.command != "manual_joint_control"
        if self._pose_move is not None and self._pose_status == "moving":
            self._pose_fail("Stop the saved-pose move before changing control or recording")
            return True
        if self._pose_episode_finalizing:
            self._pose_fail("Wait for episode saving to finish")
            return True
        if command.command in {"start_task", "set_follower_source"} and getattr(self, "_manual_stop_latched", False):
            self._pose_fail("Manual stop is latched; repair required")
            return True
        if command.command == "set_follower_source" and command.follower_source == "teleop":
            leader = self._last_leader_action
            current = np.asarray(robot_state.joint_positions)
            if leader is None or self._last_leader_timestamp is None or self._leader_failures or np.max(np.abs(leader - current)) > 5:
                self._pose_fail("Align the leader with the follower (including gripper) before enabling teleop")
                return True
        if command.command == "start_recording" and self._follower_source != "teleop":
            self._pose_fail("Enable aligned teleoperation before recording a grasp")
            return True
        if command.command == "start_recording" and self._saved_poses:
            target = self._saved_poses.get(self._approach_pose)
            if target is None or np.max(np.abs(np.asarray(robot_state.joint_positions)[:5] - target[:5])) > 2:
                self._pose_fail("Reach the selected approach before starting a grasp episode")
                return True
        if command.command in {"start_task", "set_follower_source"} and self._pose_status == "holding_target":
            self._pose_move = None
            self._pose_status = "stopped"
        return False
