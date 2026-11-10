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
        for m in ("KIOSK-A", "KIOSK-C", "center", ""):
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
        cid = self.svc.create_claim(web_payload(item_id="A-W02", quiz=[{"field": "mark", "passed": False}]))["claim_id"]
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


class KioskAutoCaptureTest(unittest.TestCase):
    """11/6 습득자 화면: 찍기 버튼 없이 자동 촬영 + 품목 놓는 법(11/9 운영 품목 5종) + 연락처 이용 목적 안내(브라우저 실행은 Playwright 로 확인)"""

    def test_page_has_auto_capture_guide_and_privacy_notice(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('id="shoot"', html)                      # 찍기 버튼 없음
        for word in ("stillMs: 5000", "getUserMedia", "trueEmpty"):      # 정지 3초(11/8) 자동 촬영, 접수 뒤 남은 물건 재촬영 방지
            self.assertIn(word, html)
        for cat in ("휴대폰", "보조배터리", "핸드크림", "카드지갑"):          # 11/10 보관함 열 순서·카드지갑 이름, 11/8 화면 이름(값은 모형폰 그대로), 11/9 품목 4종
            self.assertIn(f"<b>{cat}", html)
        self.assertNotIn("립밤", html)                               # 11/9 운영 품목에서 뺌(놓는 법·분실 확인 품목 버튼·시연 물건)
        self.assertNotIn("<b>USB", html)                              # 11/9 10:06 품목 4종 고정(USB 뺌)
        from agents.contracts import ACTIVE_CATEGORIES
        self.assertIn("const CATS = [" + ",".join(f"'{c}'" for c in ACTIVE_CATEGORIES) + "]", html)   # contracts.ACTIVE_CATEGORIES 와 같은 차례
        self.assertIn("'모형폰'", html)                            # 서버로 보내는 품목 값은 계약(CATEGORIES) 그대로
        self.assertNotIn("<b>모형폰", html)
        self.assertIn("다른 목적으로 쓰거나 다른 곳에 주지 않아요", html)
        self.assertNotIn("서버 없이 가짜 응답", html)

    def test_camera_selection_prefers_usb_and_is_configurable(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        for word in ("enumerateDevices", "kioskCamera", "camsetup", "ideal: 1920", "isSecureContext"):
            self.assertIn(word, html)
        self.assertNotIn("facingMode:'environment'", html)          # 태블릿 뒷면 카메라를 잡지 않게

    def test_no_file_upload_and_camera_down_notice_and_demo_mode(self):
        """11/8: 주운 사람이 기계 앞에서 쓰므로 사진 파일 접수 없음 · 카메라가 없으면 점검 안내 · 직원용 ?demo=1 가상 카메라"""
        from pathlib import Path
        html = (Path(__file__).resolve().parents[1] / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("사진 파일로 접수", html)
        self.assertNotIn('type="file"', html)
        self.assertIn("<h2>카메라 점검 중</h2>", html)
        self.assertIn("역무실에 알려 주세요", html)
        for word in ("openMs: 8000", "NotAllowed", "NoFrameError", "get('demo') === '1'", "captureStream", "function gotPhoto(blob)"):
            self.assertIn(word, html)
        self.assertIn('inputmode="tel"', html)
