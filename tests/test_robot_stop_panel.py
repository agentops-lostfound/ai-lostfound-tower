"""가짜 통신 작업자를 사용하는 로컬 조작 화면 HTTP 시험."""
import http.client
from http.server import ThreadingHTTPServer
import json
import threading
import unittest

from tools.robot_stop_panel import make_handler


class FakeWorker:
    def __init__(self):
        self.calls = []

    def request(self, operation, session=None):
        self.calls.append((operation, session))
        return {"ok": True, "session": "fake-session"}


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
