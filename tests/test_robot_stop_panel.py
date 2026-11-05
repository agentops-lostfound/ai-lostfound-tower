"""가짜 통신 작업자를 사용하는 로컬 조작 화면 HTTP 시험."""
import http.client
from http.server import ThreadingHTTPServer
import json
import threading
import unittest

from tools.robot_stop_panel import make_handler, HomeController
from robot.home_profiles import load_home


class FakeWorker:
    def __init__(self):
        self.calls = []

    def request(self, operation, session=None):
        self.calls.append((operation, session))
        return {"ok": True, "session": "fake-session"}


class BlockingHomeWorker:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def request(self, operation, session=None, **fields):
        self.entered.set()
        if not self.release.wait(3):
            return {"ok": False, "error": "시험 시간 초과"}
        return {"ok": True, "home_result": {"result": "HOME_REACHED"}}


class StopPanelTests(unittest.TestCase):
    def setUp(self):
        self.status = FakeWorker()
        self.stop = FakeWorker()
        # 먼저 빈 서버를 바인딩해서 테스트용 포트를 확보한다.
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = make_handler(self.status, self.stop, "test-token", self.port)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(2)

    def request(self, method, path, body=None, **headers):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_page_loading_does_not_send_commands(self):
        status, content = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("정지 요청".encode(), content)
        self.assertEqual(self.status.calls + self.stop.calls, [])

    def test_status_uses_separate_worker(self):
        status, _ = self.request("GET", "/status", **{"X-LF-Token": "test-token"})
        self.assertEqual(status, 200)
        self.assertEqual(self.status.calls, [("status", None)])
        self.assertEqual(self.stop.calls, [])

    def test_stop_requires_token_and_same_origin(self):
        for headers in ({}, {"X-LF-Token": "test-token", "Origin": "https://example.invalid"}):
            status, _ = self.request("POST", "/stop", '{"session":"fake-session"}', **headers)
            self.assertEqual(status, 403)
        self.assertEqual(self.stop.calls, [])

    def test_stop_pins_observed_session_and_never_resumes(self):
        headers = {"X-LF-Token": "test-token", "Content-Type": "application/json"}
        status, _ = self.request("POST", "/stop", '{"session":"fake-session"}', **headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.stop.calls, [("stop", "fake-session")])
        for path in ("/resume", "/home", "/action"):
            status, _ = self.request("POST", path, "{}", **headers)
            self.assertEqual(status, 404)
        self.assertEqual(len(self.stop.calls), 1)

    def test_bad_request_does_not_send_stop(self):
        for body in ("[]", "{}", "{", '{"session":12}'):
            status, _ = self.request("POST", "/stop", body, **{"X-LF-Token": "test-token"})
            self.assertEqual(status, 400)
        self.assertEqual(self.stop.calls, [])

    def add_home(self):
        worker = BlockingHomeWorker()
        controller = HomeController(worker, self.stop, lambda: load_home(store="/nonexistent-test-home-store"))
        self.server.RequestHandlerClass = make_handler(self.status, self.stop, "test-token", self.port, controller)
        self.addCleanup(controller.close)
        self.addCleanup(worker.release.set)
        return worker, controller

    def test_stop_remains_responsive_while_home_is_running(self):
        worker, controller = self.add_home()
        headers = {"X-LF-Token": "test-token"}
        status, _ = self.request("POST", "/home", json.dumps({"session": "fake-session", "epoch": 2,
                                                              "staff_confirmed": True}), **headers)
        self.assertEqual(status, 202)
        self.assertTrue(worker.entered.wait(1))
        status, response = self.request("GET", "/home-status", **headers)
        self.assertEqual(json.loads(response)["state"], "running")
        status, _ = self.request("POST", "/stop", '{"session":"fake-session"}', **headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.stop.calls, [("stop", "fake-session")])
        self.assertEqual(controller.status()["state"], "running")

    def test_home_requires_confirmation_and_rejects_duplicate_start(self):
        worker, controller = self.add_home()
        headers = {"X-LF-Token": "test-token"}
        body = {"session": "fake-session", "epoch": 2}
        status, _ = self.request("POST", "/home", json.dumps(body), **headers)
        self.assertEqual(status, 400)
        self.assertFalse(worker.entered.is_set())
        body["staff_confirmed"] = True
        status, _ = self.request("POST", "/home", json.dumps(body), **headers)
        self.assertEqual(status, 202)
        status, _ = self.request("POST", "/home", json.dumps(body), **headers)
        self.assertEqual(status, 409)

    def test_home_rejected_before_start_does_not_stop_another_task(self):
        class RejectedHome:
            def request(self, *args, **kwargs):
                return {"ok": False, "not_started": True, "error": "다른 작업이 진행 중입니다"}
        controller = HomeController(RejectedHome(), self.stop,
                                    lambda: load_home(store="/nonexistent-test-home-store"))
        controller.start("fake-session", 2, staff_confirmed=True)
        controller.thread.join(2)
        self.assertEqual(controller.status()["state"], "error")
        self.assertEqual(self.stop.calls, [])
        with self.assertRaises(RuntimeError):
            controller.start("fake-session", 2, staff_confirmed=True)

    def add_settings(self, capture_pose=None):
        from tools.robot_home_settings import HomeSettingsController
        profile = load_home(store="/nonexistent-test-home-store")
        class HeldWorker(FakeWorker):
            def request(self, operation, session=None):
                return {**super().request(operation, session), "epoch": 2,
                        "stop_requested": True, "hold_commanded": True}
        worker = HeldWorker()
        saved = []
        if capture_pose is None:
            capture_pose = lambda session, epoch: {"owner_session": session, "epoch": epoch,
                "movement_commands_sent": 0, "positions": list(profile["positions"])}
        def save(candidate, name):
            saved.append(name)
            return {"movement_commands_sent": 0, "name": name, "revision": 2}
        controller = HomeSettingsController(capture_pose, save, worker, lambda: profile, threading.Lock())
        self.server.RequestHandlerClass = make_handler(worker, self.stop, "test-token", self.port,
                                                       settings_controller=controller)
        self.addCleanup(controller.close)
        return controller, saved

    def test_settings_http_capture_preview_save_and_no_motion(self):
        controller, saved = self.add_settings()
        headers = {"X-LF-Token": "test-token"}
        body = {"session": "fake-session", "epoch": 2, "staff_confirmed": True}
        status, _ = self.request("POST", "/home-capture", json.dumps(body), **headers)
        self.assertEqual(status, 202)
        controller.thread.join(2)
        status, payload = self.request("GET", "/home-settings", **headers)
        preview = json.loads(payload)
        self.assertEqual(preview["state"], "preview")
        self.assertEqual(saved, [])
        status, _ = self.request("POST", "/home-save", json.dumps({**body,
            "candidate_id": preview["candidate_id"], "name": "보관함 옆 대기"}), **headers)
        self.assertEqual(status, 200)
        self.assertEqual(saved, ["보관함 옆 대기"])
        self.assertEqual(self.stop.calls, [])

    def test_settings_requires_token_origin_and_confirmation(self):
        controller, saved = self.add_settings()
        body = json.dumps({"session": "fake-session", "epoch": 2, "staff_confirmed": True})
        for path in ("/home-capture", "/home-save"):
            for headers in ({}, {"X-LF-Token": "test-token", "Origin": "https://example.invalid"}):
                status, _ = self.request("POST", path, body, **headers)
                self.assertEqual(status, 403)
        status, _ = self.request("POST", "/home-capture", '{"session":"fake-session","epoch":2}',
                                 **{"X-LF-Token": "test-token"})
        self.assertEqual(status, 400)
        self.assertIsNone(controller.thread)
        self.assertEqual(saved, [])

    def test_stop_is_responsive_during_pose_capture(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def capture(session, epoch):
            entered.set()
            release.wait(2)
            return {"owner_session": session, "epoch": epoch, "movement_commands_sent": 0,
                    "positions": [0.] * 6}
        controller, saved = self.add_settings(capture)
        headers = {"X-LF-Token": "test-token"}
        status, _ = self.request("POST", "/home-capture", json.dumps({"session": "fake-session",
            "epoch": 2, "staff_confirmed": True}), **headers)
        self.assertEqual(status, 202)
        self.assertTrue(entered.wait(1))
        status, _ = self.request("POST", "/stop", '{"session":"fake-session"}', **headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.stop.calls, [("stop", "fake-session")])
        self.assertEqual(saved, [])
        release.set()
        controller.thread.join(2)
