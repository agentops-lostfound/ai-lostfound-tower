"""실제 USB/네트워크 연결 없는 소유자 명령 관문 시험."""
import threading
import unittest

from robot.command_gate import CommandGate


class CommandGateTests(unittest.TestCase):
    def make_gate(self):
        calls = []
        gate = CommandGate(send=lambda goal: calls.append(goal), hold=lambda: calls.append("hold"))
        return gate, calls

    def test_start_requires_hold_and_confirmation(self):
        gate, calls = self.make_gate()
        with self.assertRaises(RuntimeError):
            gate.resume(staff_confirmed=True)
        gate.service()
        with self.assertRaises(PermissionError):
            gate.resume()
        token = gate.resume(staff_confirmed=True)
        self.assertTrue(gate.submit(token, "move"))
        gate.service()
        self.assertEqual(calls, ["hold", "move"])

    def test_stop_discards_queued_goal_and_old_token(self):
        gate, calls = self.make_gate()
        gate.service()
        token = gate.resume(staff_confirmed=True)
        gate.submit(token, "old")
        gate.request_stop()
        gate.service()
        gate.resume(staff_confirmed=True)
        self.assertFalse(gate.submit(token, "late inference"))
        gate.service()
        self.assertEqual(calls, ["hold", "hold"])

    def test_failed_hold_blocks_resume(self):
        def fail():
            raise OSError("통신 실패")
        gate = CommandGate(send=lambda goal: None, hold=fail)
        with self.assertRaises(OSError):
            gate.service()
        with self.assertRaises(RuntimeError):
            gate.resume(staff_confirmed=True)

    def test_stop_does_not_wait_for_inflight_io(self):
        entered = threading.Event()
        release = threading.Event()
        initialized = threading.Event()
        dispatch = threading.Event()
        finish = threading.Event()
        errors = []
        calls = []
        def send(goal):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("시험 동기화 실패")
            calls.append(goal)
        gate = CommandGate(send=send, hold=lambda: calls.append("hold"))
        def owner():
            try:
                gate.service()
                initialized.set()
                if not dispatch.wait(3):
                    raise TimeoutError("시험 동기화 실패")
                gate.service()
                gate.service()  # 실행 중 I/O 완료 후 유지 처리
            except Exception as error:
                errors.append(error)
            finally:
                finish.set()
        worker = threading.Thread(target=owner, daemon=True)
        worker.start()
        try:
            self.assertTrue(initialized.wait(3))
            token = gate.resume(staff_confirmed=True)
            gate.submit(token, "already_inflight")
            dispatch.set()
            self.assertTrue(entered.wait(3))
            gate.request_stop()
            self.assertFalse(gate.submit(token, "after_stop"))
            self.assertFalse(finish.is_set())
        finally:
            dispatch.set()
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(calls, ["hold", "already_inflight", "hold"])

    def test_failed_send_latches_stop(self):
        def fail(goal):
            raise OSError("전송 실패")
        gate = CommandGate(send=fail, hold=lambda: None)
        gate.service()
        token = gate.resume(staff_confirmed=True)
        gate.submit(token, "move")
        with self.assertRaises(OSError):
            gate.service()
        self.assertFalse(gate.submit(token, "retry"))
        with self.assertRaises(RuntimeError):
            gate.resume(staff_confirmed=True)
