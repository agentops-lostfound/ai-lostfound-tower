"""제한 이동/외부 정지/통신 실패의 제어 경계 모의 시험."""
import json
import unittest

from robot.owner_bridge import OwnerBridge
from tools.robot_bounded_stop_trial import MAX_DELTA, run_trial


class FakeClient:
    def __init__(self, *, stop_after=None, fail_after=None, stop_countdown=False):
        self.targets = []
        self.position = [0., 0., 0., 0., 0., 50.]
        self.stop_after = stop_after
        self.fail_after = fail_after
        self.stop_countdown = stop_countdown
        self.status_calls = 0
        self.operations = []
        self.bridge = OwnerBridge(send=self.send, hold=lambda: None)
        self.bridge.tick()

    def send(self, target):
        self.targets.append(target)
        self.position = list(target)

    def rpc(self, operation, **fields):
        self.operations.append(operation)
        if operation == "status":
            self.status_calls += 1
            if self.stop_countdown and self.status_calls == 2:
                self.bridge.receive(json.dumps({"version": self.bridge.VERSION,
                    "session": self.bridge.session, "op": "stop"}).encode())
            if self.stop_after is not None and len(self.targets) >= self.stop_after:
                self.stop_after = None
                self.bridge.receive(json.dumps({"version": self.bridge.VERSION,
                    "session": self.bridge.session, "op": "stop"}).encode())
        if operation == "action" and self.fail_after is not None and len(self.targets) >= self.fail_after:
            raise TimeoutError("통신 실패")
        response = self.bridge.receive(json.dumps({"version": self.bridge.VERSION,
            "session": self.bridge.session, "op": operation, **fields}).encode())
        self.bridge.tick()
        return response

    def positions(self):
        return list(self.position)


def run(client, **options):
    return run_trial(client, sleep=lambda seconds: None, emit=lambda *a, **k: None, **options)


class BoundedStopTests(unittest.TestCase):
    def test_no_confirmation_no_commands(self):
        client = FakeClient()
        with self.assertRaises(RuntimeError):
            run(client)
        self.assertEqual(client.operations, [])

    def test_manual_stop_blocks_remaining_targets_without_return(self):
        client = FakeClient(stop_after=5)
        result = run(client, confirmed=True)
        self.assertEqual(result["result"], "MANUAL_STOP_OBSERVED")
        self.assertEqual(len(client.targets), 5)
        self.assertTrue(result["hold_commanded_after_trial"])
        self.assertFalse(result["automatic_return"])
        self.assertEqual(result["post_stop_span_normalized"], [0.]*6)
        self.assertEqual(client.position, list(client.targets[-1]))

    def test_without_button_finishes_bounded_and_stops(self):
        client = FakeClient()
        result = run(client, confirmed=True)
        self.assertEqual(result["result"], "MANUAL_STOP_NOT_OBSERVED")
        self.assertLessEqual(max(target[0] for target in client.targets), MAX_DELTA)
        self.assertTrue(all(target[1:] == (0., 0., 0., 0., 50.) for target in client.targets))
        self.assertTrue(client.bridge.status()["stop_requested"])
        self.assertEqual(client.operations.count("resume"), 1)

    def test_stop_during_countdown_never_resumes(self):
        client = FakeClient(stop_countdown=True)
        with self.assertRaisesRegex(RuntimeError, "이동 취소"):
            run(client, confirmed=True)
        self.assertNotIn("resume", client.operations)
        self.assertEqual(client.targets, [])

    def test_action_failure_still_requests_stop(self):
        client = FakeClient(fail_after=2)
        with self.assertRaises(TimeoutError):
            run(client, confirmed=True)
        self.assertTrue(client.bridge.status()["stop_requested"])
        self.assertEqual(len(client.targets), 2)

    def test_invalid_initial_state_prevents_resume(self):
        client = FakeClient()
        client.position[0] = 99.
        with self.assertRaises(RuntimeError):
            run(client, confirmed=True)
        self.assertNotIn("resume", client.operations)
        self.assertEqual(client.targets, [])


class HomeOffsetTests(unittest.TestCase):
    def setUp(self):
        from robot.home_profiles import load_home
        self.profile = load_home(store="/nonexistent-offset-test")
        self.client = FakeClient()
        self.client.position = list(self.profile["positions"])
        self.client.position[0] += 0.3

    def test_offset_is_anchored_to_home_and_does_not_accumulate(self):
        result = run(self.client, confirmed=True, home_profile=self.profile)
        self.assertEqual(result["result"], "HOME_OFFSET_SEQUENCE_COMPLETE")
        self.assertTrue(result["offset_reached"])
        home = self.profile["positions"][0]
        self.assertAlmostEqual(self.client.position[0], home + 0.8)
        self.assertTrue(all(abs(target[0] - home) <= 0.8 + 1e-6 for target in self.client.targets))
        count = len(self.client.targets)
        repeated = run(self.client, confirmed=True, home_profile=self.profile)
        self.assertEqual(repeated["result"], "HOME_OFFSET_ALREADY_REACHED")
        self.assertEqual(len(self.client.targets), count)
        self.assertEqual(result["request_acknowledgement"], "queued_only")
        self.assertEqual(result["position_trace"][-1]["sequence"], 60)

    def test_other_joint_or_distant_pose_is_rejected_without_resume(self):
        for index, delta in ((0, 1.1), (1, 0.3)):
            client = FakeClient()
            client.position = list(self.profile["positions"])
            client.position[index] += delta
            with self.assertRaises(RuntimeError):
                run(client, confirmed=True, home_profile=self.profile)
            self.assertNotIn("resume", client.operations)
            self.assertEqual(client.targets, [])

    def test_offset_preserves_external_stop(self):
        self.client.stop_after = 5
        result = run(self.client, confirmed=True, home_profile=self.profile)
        self.assertEqual(result["result"], "MANUAL_STOP_OBSERVED")
        self.assertEqual(len(self.client.targets), 5)
        self.assertTrue(result["hold_commanded_after_trial"])
