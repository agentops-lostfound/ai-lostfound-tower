"""관리자 로그인과 /api/ 주소 체계 시험 (LF-2)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.admin_auth import MAX_FAILS, AdminAuth  # noqa: E402

try:
    from fastapi.testclient import TestClient
except ImportError:           # pragma: no cover
    TestClient = None


class AdminAuthUnit(unittest.TestCase):
    def test_off_when_no_password(self):
        a = AdminAuth("")
        self.assertFalse(a.enabled)
        self.assertTrue(a.allowed())

    def test_login_and_token(self):
        a = AdminAuth("pw", secret="s")
        self.assertIsNone(a.login("틀림", "ip"))
        tok = a.login("pw", "ip", now=1000)
        self.assertTrue(a.valid_token(tok, now=1001))
        self.assertFalse(a.valid_token(tok, now=1000 + a.ttl + 1))       # 만료
        self.assertFalse(a.valid_token(tok + "x", now=1001))             # 위조
        self.assertFalse(a.valid_token("", now=1001))

    def test_lockout_after_fails(self):
        a = AdminAuth("pw", secret="s")
        for _ in range(MAX_FAILS):
            self.assertIsNone(a.login("x", "ip", now=100))
        self.assertTrue(a.locked("ip", now=101))
        self.assertIsNone(a.login("pw", "ip", now=101))                  # 맞아도 잠금 중
        self.assertIsNotNone(a.login("pw", "ip", now=100 + 61))          # 1분 뒤 풀림

    def test_api_key(self):
        a = AdminAuth("pw", api_key="k")
        self.assertTrue(a.allowed(api_key="k"))
        self.assertFalse(a.allowed(api_key="nope"))
        self.assertFalse(AdminAuth("pw").allowed(api_key="k"))           # 키를 안 정했으면 통하지 않음


@unittest.skipUnless(TestClient, "fastapi/httpx required")
class AdminApi(unittest.TestCase):
    def client(self, **auth):
        from agents.api import build_app
        from agents.service import TowerService, demo_backend_factory
        from discord_ops.reporter import Reporter
        svc = TowerService(demo_backend_factory(), Reporter())
        return TestClient(build_app(svc, admin_auth=AdminAuth(**auth)))

    def test_open_when_auth_off(self):
        c = self.client()
        self.assertEqual(c.get("/api/admin/live/state").status_code, 200)
        self.assertEqual(c.get("/live/state").status_code, 200)
        self.assertEqual(c.get("/api/admin/me").json(), {"auth": False, "logged_in": True})
        self.assertFalse(c.get("/health").json()["admin_auth"])

    def test_admin_routes_need_login(self):
        c = self.client(password="pw", secret="s")
        for path in ("/api/admin/live/state", "/live/state", "/api/admin/returns", "/returns",
                     "/api/admin/robot/state", "/robot/state", "/api/admin/claims/C-1", "/claims/C-1"):
            self.assertEqual(c.get(path).status_code, 401, path)
        for path in ("/api/admin/robot/home", "/robot/home", "/api/admin/returns", "/returns"):
            self.assertEqual(c.post(path, json={}).status_code, 401, path)
        self.assertEqual(c.post("/api/admin/login", json={"password": "틀림"}).status_code, 401)
        self.assertEqual(c.get("/api/admin/live/state").status_code, 401)
        self.assertEqual(c.post("/api/admin/login", json={"password": "pw"}).status_code, 200)
        self.assertEqual(c.get("/api/admin/live/state").status_code, 200)
        self.assertEqual(c.get("/live/state").status_code, 200)          # 예전 주소도 같은 세션
        self.assertEqual(c.get("/api/admin/me").json(), {"auth": True, "logged_in": True})
        c.post("/api/admin/logout")
        self.assertEqual(c.get("/api/admin/live/state").status_code, 401)

    def test_public_routes_and_stop_stay_open(self):
        c = self.client(password="pw", secret="s")
        self.assertEqual(c.post("/api/robot/stop").status_code, 200)     # 정지는 항상 열림
        self.assertEqual(c.post("/robot/stop").status_code, 200)
        self.assertEqual(c.get("/api/kiosk/places", params={"machine_id": "KIOSK-A"}).status_code,
                         c.get("/places", params={"machine_id": "KIOSK-A"}).status_code)
        self.assertNotEqual(c.get("/api/kiosk/places", params={"machine_id": "KIOSK-A"}).status_code, 401)
        # 분실 접수는 로그인 없이 문지기를 통과해야 한다(본문이 틀려 422 가 나오는 것은 정상)
        for path in ("/api/lost/claims", "/api/kiosk/claims", "/api/kiosk/items"):
            self.assertEqual(c.post(path, json={}).status_code, 422, path)

    def test_api_key_header(self):
        c = self.client(password="pw", secret="s", api_key="botkey")
        self.assertEqual(c.get("/live/state").status_code, 401)
        self.assertEqual(c.get("/live/state", headers={"X-Admin-Key": "botkey"}).status_code, 200)

    def test_lockout_returns_429(self):
        c = self.client(password="pw", secret="s")
        for _ in range(MAX_FAILS):
            self.assertEqual(c.post("/api/admin/login", json={"password": "x"}).status_code, 401)
        self.assertEqual(c.post("/api/admin/login", json={"password": "pw"}).status_code, 429)


if __name__ == "__main__":
    unittest.main()
