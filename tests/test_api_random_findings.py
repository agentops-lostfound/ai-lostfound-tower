"""11/8 관제탑 API 무작위·경계값 시험(약 5,500건)에서 찾은 허점 — 다시 생기지 않게"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi.testclient import TestClient
except ImportError:           # pragma: no cover
    TestClient = None

from agents.admin_auth import AdminAuth  # noqa: E402
from agents.intake import IntakeError, MemoryIntakeStore, parse_intake  # noqa: E402

CLAIM = {"consent": True, "name_masked": "김*수", "id_no_masked": "******-1******", "id_verified": True,
         "description": {"category": "지갑"}, "item_id": "A-W01", "quiz": [{"field": "mark", "passed": True}],
         "visit_date": "2026-11-09"}
GATES = dict.fromkeys(("consent", "id_verified", "quiz_passed", "visitor_id_match", "inner_feature_ok", "staff_confirmed"), True)


@unittest.skipIf(TestClient is None, "fastapi 없음")
class ApiFindingsTest(unittest.TestCase):
    def client(self, **auth):
        from agents.api import build_app
        from agents.service import TowerService, demo_backend_factory
        from discord_ops.reporter import Reporter
        self.svc = TowerService(demo_backend_factory(), Reporter())
        return TestClient(build_app(self.svc, admin_auth=AdminAuth(**auth)))

    def test_non_ascii_cookie_is_401_not_500(self):
        a = AdminAuth("pw", secret="s")                      # 실제 HTTP 에서는 500 이었음(TestClient 는 비ASCII 쿠키를 못 보냄)
        self.assertFalse(a.valid_token("1.é"))
        self.assertFalse(a.allowed(cookie="1.é"))

    def test_public_claim_cannot_self_certify(self):
        c = self.client(password="pw", secret="s", api_key="k")
        r = c.post("/api/lost/claims", json=CLAIM).json()
        self.assertEqual(r["web_gates"], {"consent": True, "id_verified": False, "quiz_passed": False})   # 미확인으로 저장
        r = c.post("/api/lost/claims", json={**CLAIM, "item_id": "A-W02"}, headers={"X-Admin-Key": "k"}).json()
        self.assertTrue(r["web_gates"]["quiz_passed"])                                                     # 직원·웹 서버는 그대로

    def test_second_claim_on_same_item_is_409(self):
        c = self.client()
        self.assertEqual(c.post("/api/lost/claims", json=CLAIM).status_code, 200)
        r = c.post("/api/lost/claims", json={**CLAIM, "id_no_masked": "******-2******"})
        self.assertEqual(r.status_code, 409)

    def test_no_second_return_of_delivered_item(self):
        c = self.client()
        self.assertEqual(c.post("/api/admin/returns", json={"case_id": "CASE-1", "item_id": "A-W01", **GATES}).json()["decision"], "returned")
        r = c.post("/api/admin/returns", json={"case_id": "CASE-2", "item_id": "A-W01", **GATES})
        self.assertEqual((r.status_code, r.json()["detail"]["kind"]), (409, "not_in_bin"))

    def test_stop_holds_until_home(self):
        c = self.client()
        c.post("/api/robot/stop")
        self.assertEqual(c.post("/api/admin/returns", json={"case_id": "C-S1", "item_id": "A-W03", **GATES}).status_code, 409)
        self.assertTrue(c.post("/api/admin/robot/home", json={"staff_confirmed": True}).json()["ok"])
        self.assertEqual(c.post("/api/admin/returns", json={"case_id": "C-S2", "item_id": "A-W03", **GATES}).json()["decision"], "returned")

    def test_features_need_admin_when_locked(self):
        c = self.client(password="pw", secret="s", api_key="k")
        self.assertEqual(c.post("/api/kiosk/items/A-20261108-0001/features", json={"qwen": {}}).status_code, 401)

    def test_sim_reset_needs_admin_when_locked(self):
        c = self.client(password="pw", secret="s")
        self.assertEqual(c.post("/sim/reset").status_code, 401)


class IntakeFindingsTest(unittest.TestCase):
    def test_photo_path_only_own_machine_images(self):
        base = {"machine_id": "KIOSK-A", "place_text": "출구"}
        for bad in ("notes.txt", "README.md", "photos/KIOSK-C/x.jpg", "photos/KIOSK-A/x.txt"):
            with self.assertRaises(IntakeError, msg=bad):
                parse_intake({**base, "photo_path": bad})
        for ok in ("photos/KIOSK-A/20261108-1.png", "photos/A/1.jpg"):
            self.assertEqual(parse_intake({**base, "photo_path": ok})["photo_path"], ok)
        with self.assertRaises(IntakeError):
            parse_intake({**base, "machine_id": [1]})               # 503 대신 형식 오류

    def test_features_not_overwritten(self):
        from agents.intake import parse_features
        s = MemoryIntakeStore()
        iid = s.create(parse_intake({"machine_id": "KIOSK-A", "place_text": "출구"}))["item_id"]
        q = {"qwen": {"category": "wallet", "colors": ["black"], "shape": "rectangular", "material": "leather",
                      "visible_text": "ABC", "mark": "star sticker"}}
        self.assertTrue(s.set_features(iid, parse_features(q)))
        with self.assertRaises(IntakeError):
            s.set_features(iid, parse_features(q))


if __name__ == "__main__":
    unittest.main()
