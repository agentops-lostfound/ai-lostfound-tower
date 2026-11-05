"""수동 자세 변경의 토크·정지·연결 종료 및 목표 정렬 경계 시험."""
import json
from types import SimpleNamespace
import unittest

from robot.owner_bridge import ManualPose, OwnerBridge
from tools.robot_home_snapshot import capture_state_ready

NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")


class Driver:
    JOINT_ORDER = NAMES

    def __init__(self):
        self.servo_ids = {name: i + 1 for i, name in enumerate(NAMES)}
        self.positions = [2000] * 6
        self.goals = [1000] * 6
        self.torques = [1] * 6
        self.torque_on_disconnect = True
        self.calls = []
        self.fail_goal = False
        self.on_write = None
        self.read_error = False

    def _require_connection(self):
        def read1(port, identity, address):
            return self.torques[identity - 1], -1 if self.read_error else 0, 0
        def read2(port, identity, address):
            return self.goals[identity - 1], 0, 0
        return SimpleNamespace(port_handler=None, packet_handler=SimpleNamespace(
            read1ByteTxRx=read1, read2ByteTxRx=read2))

    def _require_calibration(self):
        return SimpleNamespace(joints={name: SimpleNamespace(range_min=800, range_max=3200) for name in NAMES})

    def _read_joint_positions(self):
        return list(self.positions)

    def _write_joint_positions(self, raw):
        self.calls.append(("goal", list(raw)))
        for i, value in enumerate(raw):
            if not (self.fail_goal and i == 0):
                self.goals[i] = value
                self.torques[i] = 1  # 실제 관측된 목표 기록 시 활성화를 모사한다.
        if self.on_write:
            callback, self.on_write = self.on_write, None
            callback()

    def set_torque(self, *, enabled):
        self.calls.append(("torque", enabled))
        self.torques = [int(enabled)] * 6

    def hold(self):
        self._write_joint_positions(self.positions)

    def disconnect(self):
        if self.torque_on_disconnect:
            self.hold()
            self.set_torque(enabled=True)


class ManualPoseTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.driver = Driver()
        self.manual = ManualPose(self.driver, clock=lambda: self.now)
        self.bridge = OwnerBridge(send=self.driver._write_joint_positions,
                                  hold=self.driver.hold, manual_pose=self.manual)
        self.bridge.tick()
        self.driver.calls.clear()

    def request(self, operation, **fields):
        return self.bridge.receive(json.dumps({"version": self.bridge.VERSION,
            "session": self.bridge.session, "epoch": self.bridge.status()["epoch"],
            "op": operation, **fields}).encode())

    def enter(self):
        reply = self.request("manual_pose", staff_confirmed=True)
        self.assertTrue(reply["ok"])
        self.assertEqual(self.driver.calls, [])  # 요청 콜백에서 I/O하지 않는다.
        self.bridge.tick()
        self.assertTrue(capture_state_ready({"ok": True, **self.bridge.status()}))
        self.assertEqual(self.driver.torques, [0] * 6)
        self.driver.calls.clear()

    def return_hold(self):
        self.assertTrue(self.request("manual_hold", staff_confirmed=True)["ok"])
        self.bridge.tick()
        self.now += .21
        self.bridge.tick()

    def test_requires_explicit_confirmation_and_observed_epoch(self):
        self.assertFalse(self.request("manual_pose")["ok"])
        self.assertFalse(self.request("manual_pose", epoch=99, staff_confirmed=True)["ok"])
        self.assertEqual(self.driver.calls, [])

    def test_off_is_verified_without_goal_write_and_motion_is_blocked(self):
        self.enter()
        state = self.bridge.status()
        self.assertFalse(state["hold_commanded"])
        self.assertTrue(state["manual_pose"]["torque_off_verified"])
        self.assertFalse(self.request("resume", writer="test", staff_confirmed=True)["ok"])
        self.assertFalse(self.request("action", writer="test", sequence=1, target=[0] * 6)["ok"])
        self.assertEqual(self.driver.calls, [])

    def test_stop_and_disconnect_never_reenable_manual_torque(self):
        self.enter()
        self.request("stop")
        self.bridge.tick()
        self.driver.disconnect()
        self.assertEqual(self.driver.calls, [])
        self.assertEqual(self.driver.torques, [0] * 6)

    def test_current_pose_is_aligned_before_enabling_torque(self):
        self.enter()
        self.driver.positions = [2100] * 6
        self.return_hold()
        self.assertEqual(self.driver.goals, [2100] * 6)
        self.assertEqual(self.driver.torques, [1] * 6)
        self.assertEqual(self.driver.calls[0], ("goal", [2100] * 6))
        self.assertTrue(self.driver.torque_on_disconnect)
        self.assertEqual(self.bridge.status()["manual_pose"]["state"], "idle")
        self.assertTrue(self.bridge.status()["hold_commanded"])

    def test_stop_cancels_hold_before_any_goal_write(self):
        self.enter()
        self.request("manual_hold", staff_confirmed=True)
        self.bridge.tick()
        self.request("stop")
        self.now += .3
        self.bridge.tick()
        self.assertFalse(any(call[0] == "goal" for call in self.driver.calls))
        self.assertEqual(self.driver.torques, [0] * 6)
        self.assertEqual(self.bridge.status()["manual_pose"]["state"], "active")

    def test_stop_during_goal_io_restores_off_without_later_enable(self):
        self.enter()
        self.driver.on_write = lambda: self.request("stop")
        self.return_hold()
        self.assertEqual(self.driver.torques, [0] * 6)
        self.assertNotIn(("torque", True), self.driver.calls)
        self.assertFalse(self.driver.torque_on_disconnect)

    def test_lost_goal_write_cannot_enable_old_goal(self):
        self.enter()
        self.driver.positions = [2100] * 6
        self.driver.fail_goal = True
        self.return_hold()
        self.assertEqual(self.driver.torques, [0] * 6)
        self.assertNotIn(("torque", True), self.driver.calls)
        self.assertEqual(self.bridge.status()["manual_pose"]["state"], "error")

    def test_moving_or_out_of_range_pose_cannot_enable(self):
        self.enter()
        self.request("manual_hold", staff_confirmed=True)
        self.bridge.tick()
        self.driver.positions[0] += 3
        self.now += .21
        self.bridge.tick()
        self.assertFalse(any(call[0] == "goal" for call in self.driver.calls))
        self.assertEqual(self.driver.torques, [0] * 6)
        self.driver.positions[0] = 4000
        self.request("manual_pose", staff_confirmed=True)
        self.bridge.tick()
        self.assertFalse(capture_state_ready({"ok": True, **self.bridge.status()}))
        self.assertFalse(self.request("manual_hold", staff_confirmed=True)["ok"])

    def test_failed_torque_read_keeps_movement_blocked(self):
        self.enter()
        self.driver.read_error = True
        self.now += .3
        self.bridge.tick()
        state = self.bridge.status()
        self.assertEqual(state["manual_pose"]["state"], "error")
        self.assertFalse(state["manual_pose"]["torque_off_verified"])
        self.assertFalse(self.request("resume", writer="test", staff_confirmed=True)["ok"])
        self.assertFalse(self.driver.torque_on_disconnect)

    def test_stale_manual_verification_cannot_capture(self):
        self.enter()
        self.now += 2
        self.assertFalse(capture_state_ready({"ok": True, **self.bridge.status()}))

    def test_guard_blocks_new_start_until_verified_current_hold(self):
        import tempfile
        from pathlib import Path
        from robot.owner_bridge import guard_manual_start, MANUAL_ROBOT_ID
        with tempfile.TemporaryDirectory() as folder:
            guard = Path(folder) / "manual.json"
            self.manual.guard_file = guard
            original_set = self.driver.set_torque
            def guarded_set(*, enabled):
                if not enabled:
                    self.assertTrue(guard.exists())
                original_set(enabled=enabled)
            self.driver.set_torque = guarded_set
            self.enter()
            with self.assertRaises(RuntimeError):
                guard_manual_start(MANUAL_ROBOT_ID, guard)
            guard_manual_start("another-robot", guard)
            self.driver.positions = [2100] * 6
            self.return_hold()
            self.assertFalse(guard.exists())
            guard_manual_start(MANUAL_ROBOT_ID, guard)

    def test_guard_write_failure_never_releases_arm(self):
        def failing():
            raise OSError("guard write failure")
        self.manual.ensure_guard = failing
        self.request("manual_pose", staff_confirmed=True)
        self.bridge.tick()
        self.assertEqual(self.driver.calls, [])
        self.assertEqual(self.driver.torques, [1] * 6)
        self.assertFalse(self.bridge.status()["manual_pose"]["torque_off_verified"])
