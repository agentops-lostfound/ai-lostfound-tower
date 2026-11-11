"""11/10 키오스크 조작 화면은 하나 — agents/kiosk_control.py · 화면 연결 시험

배경: 다른 PC 에서 통합 시연 화면의 습득 키오스크를 열어 두면, 화면마다 따로 물건을 판단해 찍어서 관제탑 PC 에서 시험을 할 수 없었다.
확인하는 것
- 처음 묻는 화면이 조작 화면, 다음 화면은 보기 전용
- 조작 화면이 떠나면(소식 없음) 다른 화면이 조작 화면이 된다
- [여기서 조작하기](take)로 넘겨받고, 넘겨준 화면은 보기 전용이 된다
- 기계마다 따로, 주소 형식 검사
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.kiosk_control import KioskControl, STALE_S  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
A, B, C = "clientaaaa", "clientbbbb", "clientcccc"


class ControlTest(unittest.TestCase):
    def setUp(self):
        self.now = [100.0]
        self.k = KioskControl(clock=lambda: self.now[0])

    def test_first_screen_controls_second_watches(self):
        self.assertEqual(self.k.beat("KIOSK-A", A), {"control": True, "watchers": 0, "taken": False})
        self.assertEqual(self.k.beat("KIOSK-A", B), {"control": False, "watchers": 1, "taken": False})
        self.now[0] += 2
        self.assertTrue(self.k.beat("KIOSK-A", A)["control"])
        self.assertFalse(self.k.beat("KIOSK-A", B)["control"])
        self.assertEqual(self.k.owner("KIOSK-A"), A)

    def test_owner_leaves_then_next_screen_controls(self):
        self.k.beat("KIOSK-A", A)
        self.k.beat("KIOSK-A", B)
        self.now[0] += STALE_S - 1
        self.assertFalse(self.k.beat("KIOSK-A", B)["control"])          # 아직 조작 화면이 살아 있는 것으로 본다
        self.now[0] += 2                                                 # A 는 STALE_S 넘게 소식 없음
        r = self.k.beat("KIOSK-A", B)
        self.assertEqual((r["control"], r["taken"], r["watchers"]), (True, False, 0))
        self.assertFalse(self.k.beat("KIOSK-A", A)["control"])          # 돌아온 A 는 보기 전용

    def test_take_over(self):
        self.k.beat("KIOSK-A", A)
        r = self.k.beat("KIOSK-A", B, take=True)
        self.assertEqual((r["control"], r["taken"]), (True, True))
        self.assertFalse(self.k.beat("KIOSK-A", A)["control"])          # 넘겨준 화면은 보기 전용
        self.assertTrue(self.k.beat("KIOSK-A", A, take=True)["control"])   # 다시 가져올 수 있다
        self.assertFalse(self.k.beat("KIOSK-A", C)["control"])

    def test_machines_are_separate(self):
        self.assertTrue(self.k.beat("KIOSK-A", A)["control"])
        self.assertTrue(self.k.beat("CENTER", B)["control"])
        self.assertFalse(self.k.beat("CENTER", A)["control"])
        self.assertIsNone(self.k.owner("KIOSK-C"))


class ApiTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.kiosk_control import add_control_routes
        app = FastAPI()
        add_control_routes(app)
        self.c = TestClient(app)

    def post(self, machine, body):
        return self.c.post(f"/api/kiosk/control/{machine}", json=body)

    def test_route(self):
        self.assertEqual(self.post("KIOSK-A", {"client": A}).json()["control"], True)
        self.assertEqual(self.post("KIOSK-A", {"client": B}).json()["control"], False)
        self.assertEqual(self.post("KIOSK-A", {"client": B, "take": True}).json(), {"control": True, "watchers": 1, "taken": True})
        self.assertEqual(self.post("KIOSK-A", {"client": B, "take": "yes"}).json()["taken"], False)   # true 가 아니면 넘겨받기가 아님
        for machine, body in (("KIOSK-A", {}), ("KIOSK-A", {"client": "x"}), ("KIOSK-A", {"client": "a b c d e f"}),
                              ("bad machine!", {"client": A}), ("KIOSK-A", {"client": 12345678})):
            with self.subTest(machine=machine, body=body):
                self.assertEqual(self.post(machine, body).status_code, 422)

    def test_tower_app_has_route(self):
        from agents import observability
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        from fastapi.testclient import TestClient
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        svc = build_sim_service({"TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "0", "TOWER_SIM_QWEN_WAIT": "1"})
        svc.photo_dir = tmp.name                               # 시험 사진은 임시 폴더에
        c = TestClient(build_app(svc))
        self.addCleanup(observability.set_listener, "live-board", None)
        import base64
        jpg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(64) + b"\xff\xd9").decode()
        item = {"machine_id": "KIOSK-A", "place_text": "중앙역 승강장", "photo": jpg}
        self.assertEqual(c.post("/api/kiosk/items", json=item).status_code, 200)          # 조작 화면이 없으면 예전처럼 받는다
        self.assertTrue(c.post("/api/kiosk/control/KIOSK-A", json={"client": A}).json()["control"])
        self.assertEqual(c.post("/api/kiosk/items", json=item).status_code, 409)          # 옛 화면(화면 ID 없음)의 접수는 막는다
        self.assertEqual(c.post("/api/kiosk/items", json={**item, "client": B}).status_code, 409)     # 보기 전용 화면도
        ok = c.post("/api/kiosk/items", json={**item, "client": A})
        self.assertEqual(ok.status_code, 200, ok.text)                                      # 조작 화면의 접수만
        self.assertEqual(c.post("/api/kiosk/items", json={"machine_id": "KIOSK-A", "place_text": "x"}).status_code, 200)   # 사진 없는 접수(챗봇 등)는 그대로
        self.assertEqual(c.post("/api/kiosk/items", json={**item, "machine_id": "KIOSK-C"}).status_code, 200)   # 다른 기계는 상관없음


class PageTest(unittest.TestCase):
    def test_kiosk_page_asks_and_respects_control(self):
        html = (ROOT / "web" / "kiosk" / "index.html").read_text(encoding="utf-8")
        for needle in ("'/api/kiosk/control/' + encodeURIComponent(kiosk)", "if (!inControl) { stillSince = 0; setPhase('wait');",
                       'id="takeControl">여기서 조작하기</button>', "if (DEMO || !kiosk) return;", "if (!inControl) { reset(); return; }",
                       "window.innerWidth > 0", "setInterval(() => controlBeat(false), 2000);"):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
