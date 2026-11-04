"""근거리 Home/중단/오류/동시 제어 상태의 무장비 시험."""
import json
import unittest

from robot.home_profiles import load_home
from robot.owner_bridge import OwnerBridge
from tools.robot_home_return import run_home


class Clock:
    def __init__(self):
        self.now = 0.

    def sleep(self, duration):
        self.now += duration


class HomeClient:
    def __init__(self, position):
        self.position = list(position)
        self.targets = []
        self.operations = []
        self.stop_after = None
        self.stop_on_status = None
        self.status_count = 0
        self.fail_after = None
        self.bridge = OwnerBridge(send=self.send, hold=lambda: None)
        self.bridge.tick()

    def send(self, target):
        self.targets.append(target)
        self.position = list(target)

    def rpc(self, operation, **fields):
        self.operations.append(operation)
        if operation == "status":
            self.status_count += 1
            if ((self.stop_after is not None and len(self.targets) >= self.stop_after)
                    or self.stop_on_status == self.status_count):
                self.stop_after = None
                self.bridge.receive(json.dumps({"version": self.bridge.VERSION,
                    "session": self.bridge.session, "op": "stop"}).encode())
        if operation == "action" and self.fail_after is not None and len(self.targets) >= self.fail_after:
            raise TimeoutError("전송 실패")
        reply = self.bridge.receive(json.dumps({"version": self.bridge.VERSION,
            "session": self.bridge.session, "op": operation, **fields}).encode())
        self.bridge.tick()
        return reply

    def positions(self):
        return list(self.position)


class HomeReturnTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_home(store="/nonexistent-test-home-store")
        start = list(self.profile["positions"])
        start[0] += .8
        self.client = HomeClient(start)
        self.clock = Clock()

    def run_home(self, **options):
        parameters = dict(expected_session=self.client.bridge.session, expected_epoch=0,
                          confirmed=True, local_trial=True, sleep=self.clock.sleep,
                          clock=lambda: self.clock.now)
        parameters.update(options)
        return run_home(self.client, self.profile, **parameters)

    def test_return_is_bounded_and_stops_at_home(self):
        result = self.run_home()
        self.assertEqual(result["result"], "HOME_REACHED")
        self.assertTrue(result["hold_commanded_after_home"])
        self.assertTrue(result["stop_requested_after_home"])
        self.assertEqual(self.client.operations.count("resume"), 1)
        self.assertLessEqual(len(self.client.targets), 60)
        for target in self.client.targets:
            self.assertLessEqual(abs(target[0]-result["start"][0]), .8 + 1e-6)
            self.assertEqual(list(target[1:]), result["start"][1:])
        self.assertEqual(result["final_positions"], self.profile["positions"])

    def test_stop_during_home_does_not_retry_or_complete_route(self):
        self.client.stop_after = 8
        result = self.run_home()
        self.assertEqual(result["result"], "HOME_STOPPED")
        self.assertEqual(len(self.client.targets), 8)
        self.assertEqual(self.client.operations.count("resume"), 1)
        self.assertNotEqual(self.client.position, self.profile["positions"])
        self.assertTrue(result["hold_commanded_after_home"])

    def test_already_home_does_not_resume_or_send(self):
        self.client.position = list(self.profile["positions"])
        result = self.run_home()
        self.assertEqual(result["result"], "HOME_ALREADY_REACHED")
        self.assertNotIn("resume", self.client.operations)
        self.assertEqual(self.client.targets, [])

    def test_distant_or_other_joint_pose_is_rejected_before_resume(self):
        for joint, delta in ((0, 1.1), (1, .3), (5, .3)):
            self.client = HomeClient(self.profile["positions"])
            self.client.position[joint] += delta
            with self.assertRaises(RuntimeError):
                self.run_home()
            self.assertNotIn("resume", self.client.operations)
            self.assertEqual(self.client.targets, [])

    def test_no_staff_confirmation_or_wrong_epoch_never_resumes(self):
        with self.assertRaises(PermissionError):
            self.run_home(confirmed=False)
        with self.assertRaises(RuntimeError):
            self.run_home(expected_epoch=99)
        self.assertNotIn("resume", self.client.operations)

    def test_stop_during_countdown_cancels_without_motion(self):
        self.client.stop_on_status = 3
        result = self.run_home()
        self.assertEqual(result["result"], "HOME_STOPPED")
        self.assertNotIn("resume", self.client.operations)
        self.assertEqual(self.client.targets, [])

    def test_transmission_error_latches_stop(self):
        self.client.fail_after = 2
        result = self.run_home()
        self.assertEqual(result["result"], "HOME_ABORTED")
        self.assertTrue(result["stop_requested_after_home"])
        self.assertEqual(len(self.client.targets), 2)
        self.assertEqual(self.client.operations.count("resume"), 1)
