"""11/9 키오스크 서버 카메라(agents/kiosk_camera.py) 시험 — 설정 읽기·영상 주소·설정 없는 기계 거절·화면 연결"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.kiosk_camera import KioskCameras, add_camera_routes, parse_config  # noqa: E402


class ConfigTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_config("KIOSK-A=1, KIOSK-C=2,CENTER=fake"), {"KIOSK-A": 1, "KIOSK-C": 2, "CENTER": "fake"})
        self.assertEqual(parse_config("bad, X=abc, ../etc=1, Y=99"), {})
        self.assertEqual(parse_config(None), {})


class _Closed:
    def isOpened(self):
        return False

    def release(self):
        pass


class FeedRetryTest(unittest.TestCase):
    """11/9 저녁: 웹캠이 안 열릴 때 화면이 0.1초마다 다시 열어 경고가 쏟아지던 문제 — 실패 뒤 5초는 다시 열지 않음"""

    def test_failed_open_waits_before_retry(self):
        from agents import kiosk_camera as kc
        now = [100.0]
        calls = []

        def opener(src):
            calls.append(src)
            return _Closed()
        f = kc.CameraFeed(1, opener=opener, clock=lambda: now[0])
        f.touch()
        f._thread.join(2)
        self.assertEqual(len(calls), 1)
        self.assertIn("list_cameras", f.error)
        for _ in range(20):                       # 쉬는 동안 여러 번 touch 해도 다시 열지 않음
            f.touch()
        self.assertEqual(len(calls), 1)
        now[0] += kc.RETRY_S + 0.1                # 5초 지나면 다시 시도
        f.touch()
        f._thread.join(2)
        self.assertEqual(len(calls), 2)

    def test_dark_check(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy 필요")
        from agents.kiosk_camera import is_dark
        self.assertTrue(is_dark(np.zeros((4, 4, 3), np.uint8)))
        self.assertFalse(is_dark(np.full((4, 4, 3), 120, np.uint8)))


class RoutesTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        app = FastAPI()
        self.cams = KioskCameras({"KIOSK-A": "fake"})
        add_camera_routes(app, self.cams)
        self.c = TestClient(app)

    def tearDown(self):
        # 뒤에서 도는 카메라 읽기 줄을 멈추고 기다림 — 시험이 끝날 때 줄이 살아 있으면 CI 가 종료 중 비정상 종료(134)할 수 있음
        for f in self.cams._feeds.values():
            f._seen = -1e9
            if f._thread is not None:
                f._thread.join(3)

    def test_jpg_and_status(self):
        r = self.c.get("/api/kiosk/camera/KIOSK-A.jpg")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content[:2], b"\xff\xd8")                  # JPEG
        st = self.c.get("/api/kiosk/cameras").json()["machines"]["KIOSK-A"]
        self.assertEqual(st["source"], "fake")

    def test_unconfigured_machine_is_404(self):
        self.assertEqual(self.c.get("/api/kiosk/camera/KIOSK-C.jpg").status_code, 404)
        self.assertEqual(self.c.get("/api/kiosk/camera/KIOSK-C.mjpg").status_code, 404)

    def test_mjpeg_stream_sends_frames(self):
        r = self.c.get("/api/kiosk/camera/KIOSK-A.mjpg?frames=2")      # 화면은 끝없이, 시험은 2장만
        self.assertEqual(r.status_code, 200)
        self.assertIn("multipart/x-mixed-replace", r.headers["content-type"])
        self.assertEqual(r.content.count(b"--frame"), 2)
        self.assertIn(b"Content-Type: image/jpeg", r.content)


class KioskPageTest(unittest.TestCase):
    def test_page_has_server_mode(self):
        html = (Path(__file__).resolve().parent.parent / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        self.assertIn("SERVER_CAM = CAM_PARAM === 'server'", html)
        self.assertIn("/api/kiosk/camera/${machine}.mjpg", html)
        self.assertIn("!DEMO && !SERVER_CAM && window.isSecureContext === false", html)   # 서버 카메라는 https 없이도


if __name__ == "__main__":
    unittest.main()
