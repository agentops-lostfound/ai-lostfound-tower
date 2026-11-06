"""본센터 키오스크 회수 시험 (LF-2, 11/6) — 화면은 관문 값을 보내지 못하고 서버가 정한다."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import DECISION_RETURNED  # noqa: E402
from agents.service import Conflict, NotFound, RequestError, TowerService, demo_backend_factory  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402
from tests.test_claims import web_payload  # noqa: E402

try:
    from fastapi.testclient import TestClient
    from agents.api import build_app
except ImportError:           # pragma: no cover
    TestClient = None

ID = "******-3******"


def body(cid, **over):
    b = {"machine_id": "CENTER", "claim_id": cid, "id_no_masked": ID}
    b.update(over)
    return b


class KioskReturnTest(unittest.TestCase):
    def setUp(self):
        self.svc = TowerService(demo_backend_factory(), Reporter())
        self.cid = self.svc.create_claim(web_payload())["claim_id"]

    def test_returns_when_id_matches(self):
        out = self.svc.kiosk_return(body(self.cid))
        self.assertEqual(out["decision"], DECISION_RETURNED)
        self.assertEqual(self.svc.get_claim(self.cid)["status"], "visited")

    def test_only_center_machine(self):
        for m in ("KIOSK-A", "KIOSK-B", "center", ""):
            with self.assertRaises(RequestError):
                self.svc.kiosk_return(body(self.cid, machine_id=m))
        self.assertEqual(self.svc.get_claim(self.cid)["status"], "booked")

    def test_screen_cannot_send_gates(self):
        for extra in ({"visitor_id_match": True}, {"staff_confirmed": True}, {"quiz_passed": True}, {"case_id": "X-1"}):
            with self.assertRaises(RequestError):
                self.svc.kiosk_return({**body(self.cid), **extra})
        missing = body(self.cid)
        del missing["id_no_masked"]
        with self.assertRaises(RequestError):
            self.svc.kiosk_return(missing)

    def test_wrong_id_does_not_start_and_locks_after_three(self):
        for _ in range(3):
            with self.assertRaises(RequestError):
                self.svc.kiosk_return(body(self.cid, id_no_masked="******-1******"))
        with self.assertRaises(Conflict) as c:                       # 4번째는 맞아도 잠금
            self.svc.kiosk_return(body(self.cid))
        self.assertEqual(c.exception.kind, "locked")
        self.assertEqual(self.svc.get_claim(self.cid)["status"], "booked")   # 물건은 반환 보류로 바뀌지 않음

    def test_success_resets_fail_count(self):
        for _ in range(2):
            with self.assertRaises(RequestError):
                self.svc.kiosk_return(body(self.cid, id_no_masked="x*"))
        self.assertEqual(self.svc.kiosk_return(body(self.cid))["decision"], DECISION_RETURNED)

    def test_web_quiz_failure_blocks(self):
        cid = self.svc.create_claim(web_payload(quiz=[{"field": "mark", "passed": False}]))["claim_id"]
        with self.assertRaises(Conflict):
            self.svc.kiosk_return(body(cid))

    def test_unknown_and_bad_claim(self):
        with self.assertRaises(NotFound):
            self.svc.kiosk_return(body("C-20261103-9999"))
        with self.assertRaises(RequestError):
            self.svc.kiosk_return(body("C-1"))

    def test_same_claim_cannot_return_twice(self):
        self.svc.kiosk_return(body(self.cid))
        with self.assertRaises(Conflict):
            self.svc.kiosk_return(body(self.cid))


@unittest.skipUnless(TestClient, "fastapi/httpx required")
class KioskReturnApiTest(unittest.TestCase):
    def test_open_without_admin_login(self):
        from agents.admin_auth import AdminAuth
        svc = TowerService(demo_backend_factory(), Reporter())
        client = TestClient(build_app(svc, admin_auth=AdminAuth("pw", secret="s")))
        cid = svc.create_claim(web_payload())["claim_id"]
        self.assertEqual(client.post("/api/admin/returns", json={"claim_id": cid}).status_code, 401)   # 관리자 쪽은 그대로 잠김
        r = client.post("/api/kiosk/returns", json=body(cid, id_no_masked="x*"))
        self.assertEqual(r.status_code, 422)
        r = client.post("/api/kiosk/returns", json=body(cid))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["decision"], DECISION_RETURNED)
        self.assertEqual(client.post("/api/kiosk/returns", json=body(cid)).status_code, 409)


if __name__ == "__main__":
    unittest.main()
