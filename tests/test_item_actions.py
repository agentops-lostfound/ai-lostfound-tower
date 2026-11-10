"""11/10 직원 단추: [본센터로 회수] · [접수 취소] 시험 (가상 시연)

확인하는 것
- 회수: 보관함 열이 꽉 차 등록기계에 남은 물건 → 직원 보관 선반으로, 빈 칸이 있는 품목 → 그 칸으로. 사진 분석 전에는 거절
- 접수 취소: 아직 등록기계에 있는 물건만 지운다(가상 세계 + 화면 사건 DELETE). 회수된 물건·없는 번호는 거절
- 사진 분석을 기다리던 이야기는 '접수 취소'로 끝난다
- 키오스크 완료 화면의 취소: 방금 접수한 것만, 조작 화면에서만
"""
import base64
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import observability  # noqa: E402

JPG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(64) + b"\xff\xd9").decode()
PHONE = {"category": "phone", "colors": ["black"], "shape": "rectangle", "materials": ["plastic"], "logos_or_text": [], "sticker_status": "absent"}
CREAM = {"category": "hand_cream", "colors": ["white"], "shape": "tube", "materials": ["plastic"], "logos_or_text": [], "sticker_status": "absent"}


class ItemActionTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svc = build_sim_service({"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "0", "TOWER_SIM_QWEN_WAIT": "20"})
        self.svc.photo_dir = self.tmp.name
        self.c = TestClient(build_app(self.svc))
        self.addCleanup(observability.set_listener, "live-board", None)

    def intake(self, qwen=None, machine="KIOSK-A", client=None):
        body = {"machine_id": machine, "place_text": "해운대역 승강장", "photo": JPG}
        if client:
            body["client"] = client
        r = self.c.post("/api/kiosk/items", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        iid = r.json()["item_id"]
        if qwen is not None:
            r = self.c.post(f"/api/kiosk/items/{iid}/features", json={"qwen": qwen, "confidence": 0.85})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(self.svc.sim.wait_idle(20))
        return iid

    def row(self, iid):
        return self.svc.world.items.get(iid)

    def events(self):
        return self.c.get("/api/admin/live/state?after=0&detail=1").json()

    def test_collect_full_column_goes_to_staff_shelf(self):
        iid = self.intake(PHONE)                                  # 휴대폰 열(R1)은 시연 물건 2개로 꽉 차 있다
        self.assertEqual(self.row(iid)["status"], "등록기계 보관")
        self.assertIn(iid, self.svc.world.wait_queue)
        r = self.c.post(f"/api/admin/items/{iid}/collect")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.svc.sim.wait_idle(20))
        self.assertEqual(self.row(iid)["status"], "본센터 보관")
        self.assertEqual(self.row(iid)["loc"], "shelf")           # 직원 보관 선반
        self.assertNotIn(iid, self.svc.world.wait_queue)
        story = [s for s in self.events()["stories"] if (s.get("ids") or {}).get("item_id") == iid][-1]
        self.assertTrue(story["result"]["ok"])
        self.assertIn("직원 보관 선반", story["result"]["text"])
        self.assertEqual(self.c.post(f"/api/admin/items/{iid}/collect").status_code, 409)   # 이미 회수됨

    def test_collect_needs_category_and_known_item(self):
        iid = self.intake()                                       # 사진 분석 전
        r = self.c.post(f"/api/admin/items/{iid}/collect")
        self.assertEqual(r.status_code, 409)
        self.assertIn("사진 분석", r.json()["detail"])
        self.assertEqual(self.c.post("/api/admin/items/A-20990101-0001/collect").status_code, 404)
        self.assertEqual(self.c.post("/api/admin/items/나쁜번호/collect").status_code, 422)

    def test_stored_item_is_already_collected(self):
        iid = self.intake(CREAM)                                  # 핸드크림 열(R4)은 비어 있어 바로 보관된다
        self.assertEqual(self.row(iid)["status"], "본센터 보관")
        self.assertEqual(self.c.post(f"/api/admin/items/{iid}/collect").status_code, 409)
        r = self.c.post(f"/api/admin/items/{iid}/cancel")         # 회수된 물건은 취소할 수 없다
        self.assertEqual(r.status_code, 409)
        self.assertIn(iid, self.svc.world.items)

    def test_cancel_before_analysis_ends_story_and_removes_item(self):
        iid = self.intake()
        self.assertIn(iid, [p["item_id"] for p in self.c.get("/api/admin/intake/pending-photos").json()])
        r = self.c.post(f"/api/admin/items/{iid}/cancel")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.svc.sim.wait_idle(20))
        self.assertNotIn(iid, self.svc.world.items)
        self.assertNotIn(iid, [p["item_id"] for p in self.c.get("/api/admin/intake/pending-photos").json()])
        st = self.events()
        story = [s for s in st["stories"] if (s.get("ids") or {}).get("item_id") == iid][-1]
        self.assertIn("접수 취소", story["result"]["text"])
        dels = [e["db"] for e in st["events"] if e["channel"] == "db" and e["db"]["op"] == "DELETE" and e["db"]["table"] == "item"]
        self.assertEqual([d["key"] for d in dels], [iid])
        self.assertEqual(self.c.post(f"/api/admin/items/{iid}/cancel").status_code, 404)    # 두 번은 안 됨
        self.assertEqual(self.c.post(f"/api/kiosk/items/{iid}/features", json={"qwen": PHONE, "confidence": 0.85}).status_code, 404)   # 늦게 온 분석 결과

    def test_cancel_waiting_item(self):
        iid = self.intake(PHONE)                                  # 칸 대기 중
        self.assertEqual(self.c.post(f"/api/admin/items/{iid}/cancel").status_code, 200)
        self.assertNotIn(iid, self.svc.world.items)
        self.assertNotIn(iid, self.svc.world.wait_queue)

    def test_kiosk_cancel_only_fresh_and_from_operator(self):
        iid = self.intake()
        self.assertTrue(self.c.post("/api/kiosk/control/KIOSK-A", json={"client": "operator01"}).json()["control"])
        self.assertEqual(self.c.post(f"/api/kiosk/items/{iid}/cancel", json={"client": "watcher001"}).status_code, 409)   # 보기 전용 화면
        self.svc.world.items[iid]["received_at"] = "2026-01-01T00:00:00+09:00"                                           # 오래된 접수
        self.assertEqual(self.c.post(f"/api/kiosk/items/{iid}/cancel", json={"client": "operator01"}).status_code, 409)
        iid2 = self.intake(client="operator01")                                                                           # 조작 화면이 방금 접수
        self.assertEqual(self.c.post(f"/api/kiosk/items/{iid2}/cancel", json={"client": "operator01"}).status_code, 200)
        self.assertNotIn(iid2, self.svc.world.items)
        self.assertEqual(self.c.post("/api/kiosk/items/A-20990101-0001/cancel", json={"client": "operator01"}).status_code, 404)


class MirrorDeleteTest(unittest.TestCase):
    def test_world_delete_reaches_mirror(self):
        from agents import db_mirror
        from agents.sim_director import build_sim_service
        svc = build_sim_service({"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "0"})
        calls = []

        class M:
            def __getattr__(self, name):
                return lambda *a, **k: calls.append((name, a))
        db_mirror.attach(svc, M())
        row = svc.world.create({"machine_id": "KIOSK-A", "place_id": None, "place_text": "x", "finder": None, "photo_path": "photos/a.jpg"})
        self.assertIsNotNone(svc.world.delete_item(row["item_id"]))
        self.assertIn(("item_delete", (row["item_id"],)), calls)
        self.assertIsNone(svc.world.delete_item(row["item_id"]))                 # 없는 물건: 팀 DB 에도 요청하지 않는다
        self.assertEqual(sum(1 for c in calls if c[0] == "item_delete"), 1)


if __name__ == "__main__":
    unittest.main()
