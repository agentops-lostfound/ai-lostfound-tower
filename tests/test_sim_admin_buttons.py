"""11/11 로봇 작업대 직원 단추: 멈춘 반환 [반환 취소]·[삭제], [전체 삭제], 실물 모드 [전체 초기화](두 번 눌러 실행 — 화면 쪽).
건태 님 실물 시험에서 로봇이 움직이지 않아 '반환 중'으로 남은 휴대폰 두 개를 지울 수 없었다(11/11 오전)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from tests.test_chat_cancel_staff_override import make  # noqa: E402


def stick(d, iid):
    """로봇이 움직이지 않은 반환을 흉내: 물건은 칸에 그대로, 상태만 '반환 중'"""
    d.world.db_set_status(iid, "반환 중", changed_by="tower")


class StuckReturnTest(unittest.TestCase):
    def setUp(self):
        self.svc, self.d = make()
        self.iid = next(iter(self.d.world.items))

    def test_stuck_return_can_be_cancelled_back_to_same_slot(self):
        slot = self.d.world.slot_id_of(self.iid)
        stick(self.d, self.iid)
        self.assertTrue(self.d.stuck(self.iid))
        out = self.d.cancel_stuck_return(self.iid)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["slot"], slot)
        self.assertEqual(self.d.world.items[self.iid]["status"], "본센터 보관")
        self.assertEqual(self.d.world.slot_id_of(self.iid), slot)
        self.assertFalse(self.d.cancel_stuck_return(self.iid)["ok"])          # 두 번째는 '멈춘 반환이 아님'

    def test_stuck_return_can_be_purged_but_not_while_busy(self):
        stick(self.d, self.iid)
        self.assertFalse(self.d.purge_item(self.iid)["ok"])                    # 표시 없이는 예전처럼 막힘
        orig = self.svc.health
        self.svc.health = lambda: {**orig(), "busy": True}
        try:
            self.assertFalse(self.d.stuck(self.iid))
            self.assertFalse(self.d.purge_item(self.iid, stuck=True)["ok"])    # 반환이 진짜 진행 중이면 안 됨
            self.assertFalse(self.d.purge_all()["ok"])
        finally:
            self.svc.health = orig
        self.assertTrue(self.d.purge_item(self.iid, stuck=True)["ok"])
        self.assertNotIn(self.iid, self.d.world.items)

    def test_purge_all_removes_everything_including_stuck(self):
        self.d.world.db_set_status(self.iid, "반환 중")
        out = self.d.purge_all()
        self.assertTrue(out["ok"])
        self.assertEqual(out["kept"], [])
        self.assertEqual(self.d.world.items, {})


class ApiTest(unittest.TestCase):
    def test_routes_and_real_mode_reset_needs_force(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        svc, d = make()
        c = TestClient(build_app(svc))
        iid = next(iter(d.world.items))
        stick(d, iid)
        self.assertEqual(c.post(f"/api/admin/items/{iid}/return-cancel").status_code, 200)
        stick(d, iid)
        self.assertEqual(c.post(f"/api/admin/items/{iid}/purge").status_code, 200)       # 멈춘 반환도 [삭제]
        self.assertEqual(c.post("/api/admin/items/A-20261111-9999/return-cancel").status_code, 404)
        self.assertEqual(c.post("/api/admin/items/purge-all").status_code, 200)
        svc.taught_robot = True
        self.assertEqual(c.post("/sim/reset", json={}).status_code, 409)                 # 실물 모드: 그냥은 막힘
        self.assertEqual(c.post("/sim/reset", json={"force_real": "yes"}).status_code, 409)
        self.assertEqual(c.post("/sim/reset", json={"force_real": True}).status_code, 200)

    def test_live_page_buttons_need_two_clicks(self):
        with open(os.path.join(ROOT, "web", "live", "index.html"), encoding="utf-8") as f:
            html = f.read()
        for s in ('id="purgeAll"', "한 번 더 → 전체 삭제", "한 번 더 → 반환 취소", "한 번 더 → 전체 초기화", "force_real: true",
                  "/api/admin/items/purge-all", "/return-cancel"):
            self.assertIn(s, html)


if __name__ == "__main__":
    unittest.main()
