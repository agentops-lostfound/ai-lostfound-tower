"""11/9 키오스크 서버 카메라(agents/kiosk_camera.py) 시험 — 설정 읽기·영상 주소·설정 없는 기계 거절·화면 연결"""
import os
import sys
import time
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


class FrameFitTest(unittest.TestCase):
    """11/10 교육원: 조금 지나면 영상이 화면 왼쪽 위로 몰리고 나머지가 까맸다 — 관제탑이 준 사진이 1280×720 틀의 왼쪽 위 640×480 에만
    영상이 있었음(카메라가 다른 방식으로 다시 열릴 때). 실제 영상만 잘라 늘 같은 크기(960×720)로 내보낸다"""

    def setUp(self):
        try:
            import cv2  # noqa: F401
            import numpy as np
        except ImportError:
            self.skipTest("numpy·opencv 필요")
        self.np = np
        self.rng = np.random.default_rng(0)

    def picture(self, h, w, lo=20, hi=250):
        return self.rng.integers(lo, hi, (h, w, 3), dtype=self.np.uint8)

    def test_half_filled_frame_is_cut_to_real_picture(self):
        from agents.kiosk_camera import OUT_H, OUT_W, fit, valid_size
        bad = self.np.zeros((720, 1280, 3), self.np.uint8)
        bad[:480, :640] = self.picture(480, 640, 90)
        self.assertEqual(valid_size(bad), (640, 480))
        out, cropped = fit(bad)
        self.assertTrue(cropped)
        self.assertEqual(out.shape[:2], (OUT_H, OUT_W))
        self.assertGreater(out[:, -60:].mean(), 80)        # 오른쪽 끝·아래 끝에 까만 띠가 남지 않는다
        self.assertGreater(out[-60:].mean(), 80)

    def test_normal_frames_keep_one_output_size(self):
        from agents.kiosk_camera import OUT_H, OUT_W, fit, valid_size
        for h, w in ((720, 1280), (480, 640), (1080, 1920)):
            frame = self.picture(h, w)
            self.assertEqual(valid_size(frame), (w, h))
            out, cropped = fit(frame)
            self.assertFalse(cropped)
            self.assertEqual(out.shape[:2], (OUT_H, OUT_W))       # 중간에 카메라 화질이 바뀌어도 내보내는 크기는 같다
        wide = self.np.zeros((720, 1280, 3), self.np.uint8)
        wide[:, 160:1120] = 200                                   # 16:9 는 가운데 4:3 을 쓴다
        self.assertEqual(int(fit(wide)[0].min()), 200)

    def test_dark_scenes_are_not_mistaken_for_missing_picture(self):
        from agents.kiosk_camera import fit, valid_size
        black = self.np.zeros((720, 1280, 3), self.np.uint8)      # 렌즈 가림(전체가 까맘)
        self.assertEqual(valid_size(black), (1280, 720))
        paper = self.picture(720, 1280, 0, 4)                     # 검은 배경지: 어둡지만 값이 정확히 0 으로 이어지지 않는다
        paper[:300, :400] = 120
        self.assertEqual(valid_size(paper), (1280, 720))
        self.assertFalse(fit(paper)[1])
        odd = self.np.zeros((720, 1280, 3), self.np.uint8)        # 까만 띠처럼 보여도 남는 크기가 영상 크기답지 않으면(8의 배수 아님) 자르지 않는다
        odd[:333, :501] = 150
        self.assertEqual(valid_size(odd), (1280, 720))

    def test_feed_sends_fixed_size_and_reports_crop(self):
        from agents import kiosk_camera as kc
        np = self.np
        import cv2

        class HalfFilled:
            def isOpened(self):
                return True

            def read(self):
                img = np.zeros((720, 1280, 3), np.uint8)
                img[:480, :640] = 180
                return True, img

            def release(self):
                pass
        cams = KioskCameras({"KIOSK-A": 0}, opener=lambda src: HalfFilled())
        f = cams.feed("KIOSK-A")
        f.touch()
        for _ in range(50):
            if f.latest():
                break
            import time
            time.sleep(0.05)
        jpg = f.latest()
        self.assertIsNotNone(jpg)
        img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(img.shape[:2], (kc.OUT_H, kc.OUT_W))
        self.assertGreater(int(img.min()), 150)                    # 사진 전체가 실제 영상
        st = cams.status()["KIOSK-A"]
        self.assertIn("낮은 화질", st["warning"])
        self.assertEqual(st["size"], [kc.OUT_W, kc.OUT_H])
        f._seen = -1e9
        f._thread.join(3)


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


class FramePollTest(unittest.TestCase):
    """11/11 검은 화면 개선: 사진 한 장씩 + 번호·나이·어두움 머리말 + 읽기 멈춤 풀기"""

    def setUp(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.kiosk_camera import KioskCameras, add_camera_routes
        app = FastAPI()
        self.cams = KioskCameras({"KIOSK-A": "fake"})
        add_camera_routes(app, self.cams)
        self.c = TestClient(app)
        self.addCleanup(self.cams.stop, 1.0)

    def test_after_returns_newer_frame_with_headers(self):
        r1 = self.c.get("/api/kiosk/camera/KIOSK-A.jpg")
        s1 = int(r1.headers["X-Frame-Seq"])
        self.assertGreaterEqual(s1, 1)
        self.assertEqual(r1.headers["X-Frame-Dark"], "0")
        self.assertIn("X-Frame-Age-Ms", r1.headers)
        r2 = self.c.get(f"/api/kiosk/camera/KIOSK-A.jpg?after={s1}")
        self.assertGreater(int(r2.headers["X-Frame-Seq"]), s1)                 # 기다렸다가 더 새 사진
        self.assertEqual(r2.content[:2], b"\xff\xd8")

    def test_stalled_reader_is_released_and_reopened(self):
        import threading
        from agents import kiosk_camera as kc
        now = [100.0]
        gate = threading.Event()

        class Hang(kc.FakeSource):
            released = False

            def read(self):
                if not self.released:
                    gate.wait(2.0)                                            # 카메라 읽기가 멈춤
                return (False, None) if self.released else super().read()

            def release(self):
                self.released = True
                gate.set()

        opened = []
        f = kc.CameraFeed(0, opener=lambda src: opened.append(Hang()) or opened[-1], clock=lambda: now[0])
        f.touch()
        for _ in range(50):
            if f._cap is not None:
                break
            threading.Event().wait(0.02)
        now[0] += kc.STALL_S + 1                                               # 새 사진 없이 시간이 지남
        f.touch()
        self.assertEqual(f.stalls, 1)
        self.assertTrue(opened[0].released)                                    # 멈춘 카메라를 놓아 읽기를 풀었다
        f.stop(1.0)


class KioskPageTest(unittest.TestCase):
    def test_page_has_server_mode(self):
        html = (Path(__file__).resolve().parent.parent / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        self.assertIn("SERVER_CAM = CAM_PARAM === 'server'", html)
        self.assertIn("/api/kiosk/camera/${machine}.jpg?after=${srvSeq}", html)   # 11/11 MJPEG 대신 한 장씩(연결 6개 제한·끊김 감지)
        self.assertNotIn("new Image()", html.split("function serverOpen")[1].split("function serverStop")[0])
        for s in ("X-Frame-Seq", "X-Frame-Dark", "PC 카메라 다시 연결 중", "serverWarn('down')"):
            self.assertIn(s, html)
        self.assertIn("!DEMO && !SERVER_CAM && window.isSecureContext === false", html)
        # 11/11 2차: 서버 카메라는 보이는 캔버스에 바로 그림 — captureStream → <video> 단계가 멈추면 사진이 와도 까맸다
        srv = html.split("function serverOpen")[1].split("function serverStop")[0]
        self.assertNotIn("captureStream", srv)
        self.assertIn('<canvas id="camCanvas" hidden>', html)
        self.assertIn("function camEl() { return SERVER_CAM ? $('#camCanvas') : $('#cam'); }", html)
        self.assertIn("const v = camEl(); if (!camReady()) return null;", html)            # 자동 감지도 캔버스를 읽음   # 서버 카메라는 https 없이도



class StartScriptTest(unittest.TestCase):
    """11/9 저녁: 키오스크 영상(MJPEG)이 열려 있으면 Ctrl+C 에도 관제탑이 안 꺼지던 문제 — 3초 뒤 강제 종료 옵션"""

    def test_start_tower_has_graceful_timeout(self):
        bat = (Path(__file__).resolve().parent.parent / "tools" / "start_tower.bat").read_text(encoding="utf-8")
        self.assertIn("--timeout-graceful-shutdown 3", bat)
        self.assertIn("%TOWER_GRACE%", bat)


class BlackFrameRetryTest(unittest.TestCase):
    """11/10 교육원: 카메라가 값이 전부 0 인 빈 화면만 보내는데(조명 문제가 아님) 한 번만 다시 열고 포기해, 관제탑을 다시 켤 때까지 까만 채였다"""

    def test_keeps_reopening_until_picture_comes(self):
        try:
            import cv2  # noqa: F401
            import numpy as np
        except ImportError:
            self.skipTest("opencv·numpy 필요")
        from unittest import mock
        from agents import kiosk_camera
        opened, released = [], []

        class Cap:
            def __init__(self, n):
                self.n = n

            def isOpened(self):
                return True

            def read(self):
                frame = np.zeros((48, 64, 3), np.uint8) if self.n < 3 else np.full((48, 64, 3), 150, np.uint8)   # 세 번째 열기까지는 새까만 화면
                return True, frame

            def release(self):
                released.append(self.n)

        def opener(src):
            opened.append(len(opened) + 1)
            return Cap(len(opened))
        with mock.patch.object(kiosk_camera, "DARK_FRAMES", 2), mock.patch.object(kiosk_camera, "FPS", 200):
            feed = kiosk_camera.CameraFeed(0, opener)
            feed.touch()
            deadline = time.time() + 12
            while time.time() < deadline and not (len(opened) >= 3 and feed.latest() and not feed.dark):
                time.sleep(0.05)
            self.assertGreaterEqual(len(opened), 3, opened)       # 한 번으로 포기하지 않고 다시 열었다
            self.assertEqual(released[:2], [1, 2])                # 다시 열기 전에 앞의 카메라를 놓는다
            self.assertFalse(feed.dark)
            self.assertIsNotNone(feed.latest())
            feed.stop(2)


if __name__ == "__main__":
    unittest.main()
