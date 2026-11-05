"""관리자 로그인(재민 님 admin_auth, LF_ADMIN_PASSWORD)이 켜져도 분실물봇·관제 분석 에이전트가 읽을 수 있는지 — 11/5 변재원.
작은 HTTP 서버를 띄워 X-Admin-Key 헤더가 실제로 가는지, 401 때 안내 문구가 나오는지 확인한다(키 값은 출력하지 않음)."""
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

KEY = "test-admin-key"


class Handler(BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *a):
        pass

    def _reply(self):
        Handler.seen.append((self.command, self.path, self.headers.get("X-Admin-Key")))
        if self.headers.get("X-Admin-Key") != KEY:
            body, code = b'{"detail": null}', 401
        else:
            body, code = json.dumps({"ok": True, "returns": [], "events": [], "stories": []}).encode(), 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._reply()


class AdminKeyClientsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Handler.seen.clear()

    def test_lostfound_bot_sends_key_and_explains_401(self):
        from tools.lostfound_bot import TowerClient, TowerError
        self.assertEqual(TowerClient(self.base, admin_key=KEY).get("/live/state")["ok"], True)
        self.assertEqual(TowerClient(self.base, admin_key=KEY).post("/robot/home", {"staff_confirmed": True})["ok"], True)
        self.assertEqual([s[2] for s in Handler.seen], [KEY, KEY])
        with self.assertRaises(TowerError) as cm:
            TowerClient(self.base, admin_key="").get("/live/state")
        self.assertIn("LF_ADMIN_API_KEY", str(cm.exception))
        self.assertNotIn(KEY, str(cm.exception))
        self.assertIsNone(Handler.seen[-1][2])                   # 키가 없으면 헤더도 안 보냄

    def test_ops_analyst_reader_sends_key(self):
        from agents.ops_analyst import TowerReader
        data = TowerReader(self.base, admin_key=KEY).collect()
        self.assertIn("returns", data)
        self.assertEqual([(m, p.split("?")[0], k) for m, p, k in Handler.seen],
                         [("GET", "/returns", KEY), ("GET", "/live/state", KEY)])

    def test_key_from_env(self):
        from tools.lostfound_bot import TowerClient
        old = os.environ.get("LF_ADMIN_API_KEY")
        os.environ["LF_ADMIN_API_KEY"] = KEY
        try:
            self.assertEqual(TowerClient(self.base).admin_key, KEY)
        finally:
            if old is None:
                os.environ.pop("LF_ADMIN_API_KEY", None)
            else:
                os.environ["LF_ADMIN_API_KEY"] = old


if __name__ == "__main__":
    unittest.main()
