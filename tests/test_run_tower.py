"""11/10 관제탑이 Ctrl+C 뒤에도 안 꺼져 터미널 탭이 먹통이 되던 것 — tools/run_tower.py · 카메라 놓기 시험

확인하는 것
- 서버가 멈춘 뒤에도 끝나지 않는 일이 남아 있으면: 예전 방식(python -m uvicorn)은 프로그램이 남고, run_tower.py 는 꺼진다(실제 실행)
- 끄라는 신호 뒤 정한 시간 안에 안 멈추면 강제로 끝낸다(guard)
- 서버 카메라: stop() 하면 읽기를 멈추고 카메라를 놓으며, 그 뒤에는 다시 열지 않는다
- start_tower.bat 이 평소에는 run_tower.py 를, 개발 모드(dev)에서는 uvicorn 을 쓴다
"""
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

HANG_APP = '''
import threading, time
from fastapi import FastAPI
app = FastAPI()
@app.on_event("startup")
def s():
    threading.Thread(target=lambda: time.sleep(600), daemon=False).start()   # 끝나지 않는 일(프로그램 종료를 막음)
'''


def free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(os.name == "nt", "신호 보내기는 리눅스·맥에서만 시험(Windows 는 실물 확인)")
class ExitTest(unittest.TestCase):
    def run_and_interrupt(self, cmd: list[str]) -> tuple[bool, str]:
        try:
            import fastapi, uvicorn  # noqa: F401
        except ImportError:
            self.skipTest("fastapi·uvicorn 필요")
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "hangapp.py").write_text(HANG_APP, encoding="utf-8")
            port = free_port()
            env = {**os.environ, "PYTHONPATH": d}
            p = subprocess.Popen(cmd + ["hangapp:app", "--port", str(port), "--timeout-graceful-shutdown", "1"],
                                 env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                deadline = time.time() + 15
                import urllib.request
                while time.time() < deadline:                # 서버가 켜질 때까지
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/docs", timeout=0.5).read()
                        break
                    except Exception:
                        time.sleep(0.2)
                p.send_signal(signal.SIGINT)
                try:
                    p.wait(6)
                    return True, p.stdout.read()
                except subprocess.TimeoutExpired:
                    return False, ""
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait(5)
                p.stdout.close()

    def test_plain_uvicorn_stays_alive_but_run_tower_exits(self):
        gone, _ = self.run_and_interrupt([sys.executable, "-m", "uvicorn"])
        self.assertFalse(gone, "시험 전제: 끝나지 않는 일이 있으면 예전 방식은 프로그램이 남는다")
        gone, out = self.run_and_interrupt([sys.executable, str(ROOT / "tools" / "run_tower.py")])
        self.assertTrue(gone, "run_tower.py 는 서버가 멈추면 프로그램도 끝나야 한다")
        self.assertIn("Finished server process", out)


class GuardTest(unittest.TestCase):
    def test_guard_forces_exit_after_limit_and_keeps_old_handler(self):
        import run_tower
        if threading.current_thread() is not threading.main_thread():
            self.skipTest("신호 처리는 주 스레드에서만")
        called, exited = [], threading.Event()
        before = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, lambda s, f: called.append("old"))
            run_tower.guard(0.05, exit_fn=lambda code: exited.set())
            signal.raise_signal(signal.SIGINT)
            signal.raise_signal(signal.SIGINT)               # 두 번 눌러도 시계는 하나
            self.assertEqual(called, ["old", "old"])         # 원래 처리(서버의 정상 종료)도 그대로 불린다
            self.assertTrue(exited.wait(2), "정한 시간 뒤 강제 종료가 불려야 한다")
        finally:
            signal.signal(signal.SIGINT, before)


class CameraStopTest(unittest.TestCase):
    def test_stop_releases_and_never_reopens(self):
        from agents import kiosk_camera
        opened, released = [], threading.Event()

        class Cap:
            def isOpened(self):
                return True

            def read(self):
                time.sleep(0.01)
                return False, None

            def release(self):
                released.set()

        def opener(src):
            opened.append(src)
            return Cap()
        cams = kiosk_camera.KioskCameras({"KIOSK-A": 0}, opener=opener)
        feed = cams.feed("KIOSK-A")
        feed.touch()
        time.sleep(0.1)
        self.assertTrue(kiosk_camera.stop_all(2))            # 열려 있는 카메라를 모두 놓는다
        self.assertTrue(released.is_set())
        self.assertFalse(feed._thread.is_alive())
        feed.touch()                                         # 끈 뒤에는 다시 열지 않는다
        time.sleep(0.05)
        self.assertEqual(opened, [0])
        self.assertTrue(cams.stop(0.1))                      # 이미 멈춘 것을 또 멈춰도 괜찮다


class BatTest(unittest.TestCase):
    def test_bat_uses_run_tower_and_keeps_uvicorn_for_dev(self):
        raw = (ROOT / "tools" / "start_tower.bat").read_bytes()
        bat = raw.decode("utf-8")
        self.assertIn("python tools\\run_tower.py agents.api:app --host %TOWER_HOST% --port 8100 --no-access-log %TOWER_GRACE%", bat)
        self.assertIn("if defined TOWER_RELOAD goto run_dev", bat)
        self.assertLess(bat.index(":run_dev"), bat.index("python -m uvicorn agents.api:app"))
        for line in raw.split(b"\n"):                        # 새로 넣은 줄은 영문만(한글 Windows 의 cmd 가 깨뜨리지 않게)
            if b"run_tower" in line or b"run_dev" in line or b"run_done" in line:
                line.decode("ascii")


class QwenSetupBatTest(unittest.TestCase):
    def test_setup_qwen_bat_is_ascii_and_has_steps(self):
        raw = (ROOT / "tools" / "setup_qwen.bat").read_bytes()
        text = raw.decode("ascii")                           # 한글 Windows 의 cmd 가 깨뜨리지 않게 영문만
        self.assertIn(b"\r\n", raw)
        for needle in ("-m venv .venv-qwen", "pip install -r qwen\\requirements.txt", "scripts.check_environment --load-model",
                       "tools\\intake_qwen_worker.py --check", "if exist .venv-qwen\\Scripts\\python.exe goto have_venv"):
            self.assertIn(needle, text)
        self.assertNotIn(".env ", text)                      # 비밀값 파일을 읽거나 출력하지 않는다



class LanHintTest(unittest.TestCase):
    """11/12 lan 모드면 발표 화면 주소를 LAN 주소 하나로 안내"""

    def test_hint_only_in_lan_mode(self):
        import tools.run_tower as rt
        h = rt.lan_hint(["agents.api:app", "--host", "0.0.0.0", "--port", "8100"], ip="10.10.21.21")
        self.assertIn("http://10.10.21.21:8100/showcase?scene=found", h)
        self.assertIsNone(rt.lan_hint(["agents.api:app", "--host", "127.0.0.1", "--port", "8100"], ip="10.10.21.21"))
        self.assertIsNone(rt.lan_hint(["agents.api:app", "--port", "8100"], ip="10.10.21.21"))
        self.assertIsNone(rt.lan_hint(["agents.api:app", "--host"], ip="10.10.21.21"))     # 인자가 모자라도 오류 없음

if __name__ == "__main__":
    unittest.main()


class PortGuardTest(unittest.TestCase):
    """11/12 같은 포트에 옛 관제탑이 남아 있으면 켜지 않음(브라우저·Qwen 작업자가 서로 다른 관제탑을 보던 문제)"""

    def test_port_taken_and_refuse(self):
        import socket
        from unittest import mock
        import tools.run_tower as rt
        srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
        port = srv.getsockname()[1]
        try:
            self.assertTrue(rt.port_taken(port))
            self.assertEqual(rt.port_of(["agents.api:app", "--host", "0.0.0.0", "--port", str(port)]), port)
            self.assertIn(f"findstr :{port}", rt.taken_message(port))
            ended = []
            with mock.patch.object(rt, "finish", side_effect=lambda c=0: ended.append(c)), \
                    mock.patch.dict(os.environ, {"TOWER_PORT_GUARD": "1"}):
                rt.main(["agents.api:app", "--host", "0.0.0.0", "--port", str(port)])
            self.assertEqual(ended, [1])                       # 켜지 않고 끝냄
        finally:
            srv.close()
        self.assertFalse(rt.port_taken(port))
        self.assertEqual(rt.port_of(["x", "--port"]), 8000)

