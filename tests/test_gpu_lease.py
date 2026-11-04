"""GPU 사용권(agents/gpu_lease.py)과 관제탑 연결 시험 — 11/4."""
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents.contracts import DECISION_RETURNED, DECISION_STAFF  # noqa: E402
from agents.gpu_lease import GpuBusy, GpuLease, holder, lease_from_env  # noqa: E402
from agents.service import TowerService, demo_backend_factory, GATE_FIELDS  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class LeaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "gpu.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def test_acquire_release_and_holder(self):
        self.assertIsNone(holder(self.path))
        with GpuLease("qwen", path=self.path) as lease:
            self.assertTrue(lease.held)
            h = holder(self.path)
            self.assertEqual(h["user"], "qwen")
            self.assertEqual(h["pid"], os.getpid())
        self.assertIsNone(holder(self.path))

    def test_second_waits_then_gives_up(self):
        clock = FakeClock()
        with GpuLease("stt", path=self.path):
            other = GpuLease("vla", path=self.path, wait=3, poll=1, clock=clock, sleep=clock.sleep)
            with self.assertRaises(GpuBusy) as cm:
                other.acquire()
            self.assertIn("stt", str(cm.exception))
            self.assertEqual(cm.exception.holder["user"], "stt")
            self.assertGreaterEqual(clock.t, 3)
        with GpuLease("vla", path=self.path, wait=0):     # 반납 뒤에는 바로 받음
            pass

    def test_waiter_gets_it_after_release(self):
        first = GpuLease("qwen", path=self.path).acquire()
        got = {}

        def waiter():
            with GpuLease("vla", path=self.path, wait=5, poll=0.05) as l2:
                got["held"] = l2.held
        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.2)
        self.assertNotIn("held", got)
        first.release()
        t.join(3)
        self.assertTrue(got.get("held"))

    def test_stale_info_ignored(self):
        Path(str(self.path) + ".json").write_text('{"user": "qwen", "pid": 1, "since": 1}', encoding="utf-8")
        self.assertIsNone(holder(self.path))               # 정보 파일만 남고 잠금은 없음 → 아무도 안 씀
        with GpuLease("vla", path=self.path, wait=0):
            pass

    def test_dead_process_releases(self):
        code = ("import sys,time; sys.path.insert(0, sys.argv[1]); from agents.gpu_lease import GpuLease; "
                "l=GpuLease('qwen', path=sys.argv[2]).acquire(); print('ok', flush=True); time.sleep(30)")
        p = subprocess.Popen([sys.executable, "-c", code, ROOT, str(self.path)], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(p.stdout.readline().strip(), "ok")
            self.assertEqual(holder(self.path)["user"], "qwen")
            with self.assertRaises(GpuBusy):
                GpuLease("vla", path=self.path, wait=0).acquire()
        finally:
            p.kill()
            p.wait(5)
            p.stdout.close()
        with GpuLease("vla", path=self.path, wait=2, poll=0.05):   # 프로그램이 죽으면 열쇠가 저절로 풀림
            pass

    def test_free_memory_wait(self):
        clock = FakeClock()
        seq = iter([1200, 2500, 5000])
        lease = GpuLease("vla", path=self.path, wait=10, poll=1, need_free_mb=4000,
                         free_mb=lambda: next(seq), clock=clock, sleep=clock.sleep)
        lease.acquire()
        self.assertTrue(lease.held)
        self.assertEqual(clock.t, 2)
        lease.release()
        lease2 = GpuLease("vla", path=self.path, wait=2, poll=1, need_free_mb=4000,
                          free_mb=lambda: 1000, clock=FakeClock(), sleep=lambda s: None)
        lease2.clock = clock2 = FakeClock()
        lease2.sleep = clock2.sleep
        with self.assertRaises(GpuBusy) as cm:
            lease2.acquire()
        self.assertIn("메모리", str(cm.exception))
        self.assertIsNone(holder(self.path))                 # 실패하면 열쇠도 돌려줌
        GpuLease("vla", path=self.path, need_free_mb=4000, free_mb=lambda: None, wait=0).acquire().release()   # 못 읽으면 막지 않음

    def test_bad_user_and_env(self):
        with self.assertRaises(ValueError):
            GpuLease("누군가", path=self.path)
        self.assertIsNone(lease_from_env({"TOWER_GPU_LEASE": "0"}))
        f = lease_from_env({"TOWER_GPU_WAIT": "15", "TOWER_GPU_FREE_MB": "3500"})
        lease = f("vla")
        self.assertEqual((lease.wait, lease.need_free_mb), (15.0, 3500.0))
        lease = lease_from_env({"TOWER_GPU_WAIT": "abc"})("vla")
        self.assertEqual((lease.wait, lease.need_free_mb), (60.0, None))


class TowerGpuTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "gpu.lock"
        self.rep = Reporter()
        self.svc = TowerService(demo_backend_factory(), self.rep,
                                gpu_lease=lambda user: GpuLease(user, path=self.path, wait=0))

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, case):
        return {"case_id": case, "item_id": "A-W01", **{g: True for g in GATE_FIELDS}}

    def test_busy_gpu_blocks_robot(self):
        with GpuLease("qwen", path=self.path):
            out = self.svc.start_return(self.payload("G1"))
        self.assertEqual(out["decision"], DECISION_STAFF)
        self.assertIn("GPU 사용권 없음", out["reason"])
        self.assertIn("qwen", out["reason"])
        self.assertNotIn("사전 접근 완료", out["steps"])
        self.assertEqual(self.svc.backend_factory().db_get_item("A-W01")["status"], "승인·수령 예약")   # 반환 중으로 안 바뀜

    def test_free_gpu_used_and_returned(self):
        out = self.svc.start_return(self.payload("G2"))
        self.assertEqual(out["decision"], DECISION_RETURNED)
        self.assertIn("GPU 사용권 받음", out["steps"])
        self.assertIsNone(holder(self.path))                  # 반환이 끝나면 열쇠를 돌려줌
        self.assertEqual(self.svc.health()["gpu"]["lease"], "on")

    def test_lease_off_no_step(self):
        svc = TowerService(demo_backend_factory(), Reporter())
        out = svc.start_return(self.payload("G3"))
        self.assertNotIn("GPU 사용권 받음", out["steps"])
        self.assertEqual(svc.health()["gpu"], {"lease": "off"})


if __name__ == "__main__":
    unittest.main()
