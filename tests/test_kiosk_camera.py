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


class RoutesTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        app = FastAPI()
        add_camera_routes(app, KioskCameras({"KIOSK-A": "fake"}))
        self.c = TestClient(app)

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
