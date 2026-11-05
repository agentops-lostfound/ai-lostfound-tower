"""JSON 전송 경계 및 소유자 패치 생성의 무장비 시험."""
import ast
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from robot.owner_bridge import OwnerBridge
from tools.prepare_robot_owner_patch import OWNER_IN_ZIP, patched_source, prepare


class OwnerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.bridge = OwnerBridge(send=lambda x: self.calls.append(x),
                                  hold=lambda: self.calls.append("hold"))

    def request(self, operation, **fields):
        return self.bridge.receive(json.dumps({
            "version": self.bridge.VERSION, "session": self.bridge.session,
            "op": operation, **fields,
        }).encode())

    def resume(self):
        self.bridge.tick()
        return self.request("resume", epoch=self.bridge.status()["epoch"],
                            writer="test", staff_confirmed=True)["epoch"]

    def test_stop_ack_is_not_hold_ack(self):
        reply = self.request("stop")
        self.assertTrue(reply["stop_requested"])
        self.assertFalse(reply["hold_commanded"])
        self.assertEqual(self.calls, [])
        self.bridge.tick()
        self.assertTrue(self.request("status")["hold_commanded"])

    def test_legacy_messages_and_wrong_sessions_rejected(self):
        self.assertFalse(self.bridge.receive(b'{"action":[0,0,0,0,0,0]}')["ok"])
        self.assertFalse(self.request("stop", session="previous_owner")["ok"])
        self.assertEqual(self.calls, [])

    def test_only_confirmed_writer_can_resume_and_submit(self):
        self.assertFalse(self.request("resume", epoch=0, writer="test",
                                      staff_confirmed=True)["ok"])
        self.bridge.tick()
        self.assertFalse(self.request("resume", epoch=0, writer="test")["ok"])
        token = self.resume()
        self.assertFalse(self.request("action", epoch=token, writer="other",
                                      sequence=1, target=[0]*6)["ok"])
        self.assertTrue(self.request("action", epoch=token, writer="test",
                                     sequence=1, target=[0]*6)["ok"])
        self.bridge.tick()
        self.assertEqual(self.calls, ["hold", (0,)*6])

    def test_delayed_actions_and_resume_rejected_after_stop(self):
        old = self.resume()
        self.request("action", epoch=old, writer="test", sequence=1, target=[0]*6)
        self.request("stop")
        self.bridge.tick()
        self.assertFalse(self.request("resume", epoch=old, writer="test",
                                      staff_confirmed=True)["ok"])
        new = self.resume()
        self.assertNotEqual(old, new)
        self.assertFalse(self.request("action", epoch=old, writer="test",
                                      sequence=2, target=[0]*6)["ok"])
        self.bridge.tick()
        self.assertEqual(self.calls, ["hold", "hold"])

    def test_duplicate_out_of_order_and_invalid_targets(self):
        token = self.resume()
        self.assertTrue(self.request("action", epoch=token, writer="test",
                                     sequence=3, target=[0]*6)["ok"])
        for sequence, target in [(3, [0]*6), (2, [0]*6), (4, [0]*5),
                                 (4, [float("nan")]*6), (4, [True]*6)]:
            self.assertFalse(self.request("action", epoch=token, writer="test",
                                          sequence=sequence, target=target)["ok"])

    def test_owner_restart_invalidates_previous_session(self):
        other = OwnerBridge(send=lambda x: None, hold=lambda: None)
        payload = json.dumps({"version": other.VERSION, "session": self.bridge.session,
                              "op": "stop"}).encode()
        self.assertFalse(other.receive(payload)["ok"])

    def test_invalid_json_and_oversized_payload(self):
        for payload in (b"[1]", b"{", b"x"*8193):
            self.assertFalse(self.bridge.receive(payload)["ok"])


class PatchPreparationTests(unittest.TestCase):
    def test_unknown_archive_is_rejected_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(root / "source.zip", "w") as archive:
                archive.writestr(OWNER_IN_ZIP, "# different version")
            with self.assertRaises(ValueError):
                prepare(root / "source.zip", root / "output")
            self.assertFalse((root / "output").exists())

    def test_source_structure_change_rejected(self):
        with self.assertRaises(ValueError):
            patched_source("# changed source")

    def test_staged_bridge_import_fallback_is_valid(self):
        # 설치 경로의 상대 import는 구문으로 검증. 실제 SDK는 import하지 않는다.
        root = Path(__file__).resolve().parents[1]
        for name in ("robot/command_gate.py", "robot/owner_bridge.py"):
            ast.parse((root / name).read_text(encoding="utf-8"))


class GoalReadbackTests(unittest.TestCase):
    def make_bridge(self, *, comm=0, mismatch=False):
        import math
        from types import SimpleNamespace
        from unittest.mock import patch
        from robot.owner_bridge import for_so101
        class Array(list):
            shape = (6,)
            def astype(self, dtype):
                return self
        state = {"goal": None, "sends": 0, "reads": []}
        def send(action):
            state["sends"] += 1
            state["goal"] = round(846 + (action[0] + 100) / 200 * 2707)
        def read(port, motor_id, address, length):
            state["reads"].append((motor_id, address, length))
            goal = state["goal"] + int(mismatch)
            block = [0] * 18
            block[0] = 1
            block[2:4] = [goal & 255, goal >> 8]
            block[16:18] = [2151 & 255, 2151 >> 8]
            return block, comm, 0
        driver = SimpleNamespace(role="follower", unit="normalized", servo_ids={"shoulder_pan": 1},
            _read_joint_positions=lambda: Array([2151] * 6), _write_joint_positions=lambda x: None,
            _unit_to_ticks=lambda action: [round(846 + (action[0] + 100) / 200 * 2707)] * 6,
            send_action=send, _require_connection=lambda: SimpleNamespace(port_handler=object(),
                packet_handler=SimpleNamespace(readTxRx=read)))
        numpy = SimpleNamespace(asarray=lambda x, dtype: Array(x), float32=float, int32=int,
                                isfinite=lambda x: [math.isfinite(v) for v in x], all=all)
        with patch.dict("sys.modules", {"numpy": numpy}):
            bridge = for_so101(driver)
        bridge.tick()
        def request(op, **fields):
            return bridge.receive(json.dumps({"version": bridge.VERSION, "session": bridge.session,
                "op": op, **fields}).encode())
        epoch = request("resume", epoch=0, writer="test", staff_confirmed=True)["epoch"]
        request("action", epoch=epoch, writer="test", sequence=1,
                target=[-3.8788325786590576, 0, 0, 0, 0, 0])
        return bridge, state

    def test_queued_ack_precedes_driver_call_and_verified_goal_readback(self):
        bridge, state = self.make_bridge()
        self.assertEqual(state["sends"], 0)
        self.assertEqual(bridge.status()["delivery"]["attempts"], 0)
        bridge.tick()
        result = bridge.status()["delivery"]
        self.assertEqual(result["requested_pan_raw"], 2147)
        self.assertEqual(result["observed_goal_raw"], 2147)
        self.assertTrue(result["goal_matches_request"])
        self.assertEqual(result["driver_calls_returned"], 1)
        self.assertEqual(state["reads"], [(1, 40, 18)])
        self.assertEqual(result["observed_present_raw"], 2151)
        self.assertEqual(result["torque"], 1)

    def test_read_failure_or_goal_mismatch_latches_stop_and_preserves_evidence(self):
        for options in ({"comm": -1}, {"mismatch": True}):
            bridge, state = self.make_bridge(**options)
            with self.assertRaises(RuntimeError):
                bridge.tick()
            result = bridge.status()
            self.assertTrue(result["stop_requested"])
            self.assertEqual(result["delivery"]["stage"], "error")
            self.assertEqual(state["sends"], 1)
