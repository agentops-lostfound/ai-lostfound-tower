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
