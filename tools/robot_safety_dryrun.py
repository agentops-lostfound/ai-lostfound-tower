"""LF-11/12: 하드웨어·네트워크를 사용하지 않는 정지/Home 상태 시험.

실제 드라이버가 아니며 위치 유지나 물리적 정지 성능을 보장하지 않는다.
실행: python tools/robot_safety_dryrun.py
"""

import threading
import unittest


class DryRunController:
    """단일 명령 소유자를 흉내 내는 메모리 전용 제어기."""

    def __init__(self):
        self._lock = threading.Lock()
        self._epoch = 0
        self._stopped = False
        self.commands = []

    def ticket(self):
        with self._lock:
            if self._stopped:
                raise RuntimeError("정지 상태: 직원 확인 후 재개 필요")
            return self._epoch

    def submit(self, ticket, target):
        with self._lock:
            if self._stopped or ticket != self._epoch:
                return False
            self.commands.append(("move", target))
            return True

    def stop(self):
        with self._lock:
            self._stopped = True
            self._epoch += 1
            # 실제 위치 읽기/모터 전송이 아니다. 유지 요청을 기록할 뿐이다.
            self.commands.append(("hold_requested", None))

    def resume(self, *, staff_confirmed=False):
        if not staff_confirmed:
            raise PermissionError("직원 확인 필요")
        with self._lock:
            self._epoch += 1
            self._stopped = False

    def home(self, waypoints, *, staff_confirmed=False, before_submit=None):
        if not staff_confirmed:
            raise PermissionError("Home은 별도 직원 확인 필요")
        ticket = self.ticket()
        for point in waypoints:
            if before_submit:
                before_submit(point)
            if not self.submit(ticket, point):
                return False
        return True


class SafetyTests(unittest.TestCase):
    def test_stop_blocks_pending_and_new_motion(self):
        c = DryRunController()
        ticket = c.ticket()
        self.assertTrue(c.submit(ticket, "first"))
        c.stop()
        self.assertFalse(c.submit(ticket, "pending"))
        with self.assertRaises(RuntimeError):
            c.ticket()
        self.assertEqual(c.commands, [("move", "first"), ("hold_requested", None)])

    def test_stop_does_not_start_home(self):
        c = DryRunController()
        c.stop()
        self.assertEqual(c.commands, [("hold_requested", None)])

    def test_resume_requires_confirmation_and_rejects_old_work(self):
        c = DryRunController()
        old = c.ticket()
        c.stop()
        with self.assertRaises(PermissionError):
            c.resume()
        c.resume(staff_confirmed=True)
        self.assertFalse(c.submit(old, "stale policy result"))
        self.assertTrue(c.submit(c.ticket(), "new work"))

    def test_home_requires_confirmation(self):
        c = DryRunController()
        with self.assertRaises(PermissionError):
            c.home(["home"])
        self.assertEqual(c.commands, [])
        self.assertTrue(c.home(["clearance", "home"], staff_confirmed=True))

    def test_stop_while_home_prepares_next_command(self):
        c = DryRunController()
        preparing = threading.Event()
        release = threading.Event()
        results = []

        def prepare(point):
            if point == "second":
                preparing.set()
                if not release.wait(3):
                    raise TimeoutError("시험 동기화 실패")

        worker = threading.Thread(target=lambda: results.append(c.home(
            ["first", "second", "home"], staff_confirmed=True,
            before_submit=prepare,
        )), daemon=True)
        worker.start()
        try:
            self.assertTrue(preparing.wait(3))
            c.stop()
            # 정지 후 확인 재개를 해도 실행 중이던 Home은 되살아나면 안 된다.
            c.resume(staff_confirmed=True)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results, [False])
        self.assertEqual(c.commands, [("move", "first"), ("hold_requested", None)])


if __name__ == "__main__":
    print("DRY RUN ONLY: no robot, USB, network, or motor commands", flush=True)
    unittest.main(verbosity=2)
