"""11/8 교육원 PC(RTX 3050 6GB) 그래픽카드 안전 — 시뮬레이션 + GPU 사용권 동안 Ollama CPU·내리기 + Qwen 사진마다 내리기"""
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import local_model  # noqa: E402
from agents.gpu_lease import GpuBusy, GpuLease  # noqa: E402
from tools import gpu_budget_sim as sim  # noqa: E402
from tools import intake_qwen_worker as worker  # noqa: E402


class BudgetSimTest(unittest.TestCase):
    def test_now_overflows_lease_does_not_even_in_worst_case(self):
        worst = sim.Premise(display=(1300, 1300), vla=(3000, 3000), midm=(2400, 2400), qwen=(2700, 2700))
        now = sim.summarize("now", worst, runs=60)
        safe = sim.summarize("lease", worst, runs=60)
        self.assertGreater(now["sessions_with_oom"], 30)              # 지금 방식: 거의 모든 시연에서 넘침
        self.assertEqual(safe["sessions_with_oom"], 0)                # 고친 방식: 한 번도 안 넘침
        self.assertLessEqual(safe["peak_max"], sim.TOTAL - sim.MARGIN)
        self.assertEqual(safe["gpu_wait_fail"], 0)                    # 사진 분석(최대 20초)이 로봇을 60초 넘게 막지 않음

    def test_robot_memory_counted_only_while_running(self):
        """시뮬레이터 자체 검증(11/8 1차에서 찾은 오류): 사용권을 기다리는 동안 VLA 메모리를 세지 않는다"""
        for seed in range(80):
            r = sim.simulate("lease", sim.Premise(), seed)
            self.assertLessEqual(r.peak, sim.TOTAL - sim.MARGIN, seed)


class OllamaGuardTest(unittest.TestCase):
    def test_cpu_while_someone_holds_gpu(self):
        p = {"model": "m", "options": {"temperature": 0}}
        with mock.patch("agents.gpu_lease.holder", return_value={"user": "vla"}):
            self.assertEqual(local_model.with_gpu_guard(p)["options"], {"temperature": 0, "num_gpu": 0})
            with mock.patch.dict(os.environ, {"OLLAMA_GPU_GUARD": "0"}):
                self.assertIs(local_model.with_gpu_guard(p), p)
        with mock.patch("agents.gpu_lease.holder", return_value=None):
            self.assertIs(local_model.with_gpu_guard(p), p)
        self.assertEqual(p["options"], {"temperature": 0})          # 원래 요청은 바꾸지 않음

    def test_unload_asks_keep_alive_zero_for_each_model(self):
        calls = []

        class R:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, *_): return self.body

        class Op:
            def open(self, req, timeout=None):
                if isinstance(req, str):
                    return R(json.dumps({"models": [{"name": "midm-2.0-mini:latest"}]}).encode())
                calls.append(json.loads(req.data))
                return R(b"{}")
        with mock.patch.object(local_model, "_opener", return_value=Op()):
            self.assertEqual(local_model.unload_local_models(), ["midm-2.0-mini:latest"])
        self.assertEqual(calls, [{"model": "midm-2.0-mini:latest", "keep_alive": 0}])
        with mock.patch.object(local_model, "_opener", side_effect=OSError("down")):
            self.assertEqual(local_model.unload_local_models(), [])     # Ollama 꺼져 있어도 예외 없음


class TowerUnloadTest(unittest.TestCase):
    def test_robot_lease_unloads_ollama_and_switch(self):
        from agents.service import GuardedBackend
        with tempfile.TemporaryDirectory() as d:
            factory = lambda user: GpuLease(user, wait=0, path=Path(d) / "gpu.lock")  # noqa: E731
            with mock.patch("agents.local_model.unload_local_models") as unload:
                be = GuardedBackend(object(), threading.Event(), factory)
                self.assertEqual(be.gpu_acquire("vla"), (True, ""))
                unload.assert_called_once()
                be.gpu_release()
                with mock.patch.dict(os.environ, {"TOWER_OLLAMA_UNLOAD": "0"}):
                    be.gpu_acquire("vla")
                    be.gpu_release()
                unload.assert_called_once()                          # 꺼 두면 부르지 않음


class QwenWorkerGpuTest(unittest.TestCase):
    def test_order_lease_unload_analyze_release(self):
        log = []

        class L:
            def __enter__(self): log.append("lease"); return self
            def __exit__(self, *a): log.append("return"); return False
        run = worker.gpu_guarded(lambda p: log.append("analyze") or {"category": "지갑"}, lease=L,
                                 unload=lambda: log.append("unload ollama"), release=lambda: log.append("release qwen"))
        self.assertEqual(run(Path("x.jpg")), {"category": "지갑"})
        self.assertEqual(log, ["lease", "unload ollama", "analyze", "release qwen", "return"])
        log.clear()
        worker.gpu_guarded(lambda p: {}, keep_model=True, lease=L, unload=lambda: None,
                           release=lambda: log.append("release qwen"))(Path("x"))
        self.assertNotIn("release qwen", log)                       # 8GB PC: 계속 올려 둠

    def test_busy_gpu_is_not_a_failure(self):
        class T:
            sent = []
            def pending(self): return [{"item_id": "A-1", "photo_path": "p.jpg"}]
            def send(self, iid, f): self.sent.append(iid)

        def busy(_p):
            raise GpuBusy("GPU 사용 중(vla, 30초째)")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "p.jpg").write_bytes(b"x")
            tries, lines = {}, []
            self.assertEqual(worker.process_once(T(), busy, tries, log=lines.append, root=Path(d)), 0)
        self.assertEqual(tries, {})                                  # 실패 횟수에 안 들어감 → 로봇이 끝나면 다시
        self.assertIn("[대기]", lines[0])

    def test_check_still_exits_when_tower_down(self):
        with mock.patch.object(worker.Tower, "pending", side_effect=OSError("refused")):
            self.assertEqual(worker.main(["--check"]), 2)


if __name__ == "__main__":
    unittest.main()
