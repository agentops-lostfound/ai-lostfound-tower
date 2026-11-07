"""11/7 키오스크 사진 → Qwen 작업자 → 관제탑(LF-3 변재원).

한줄 설명: 키오스크에서 사진으로 접수한 물건이 '접수'에서 멈추던 허점(특징을 채우는 작업자가 없었음)을 고쳤는지 확인한다.
- 진짜 Qwen 모델은 쓰지 않는다(그래픽카드 없음). 분석 함수 자리에 정해진 특징을 돌려주는 대역을 끼운다
"""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.intake import MemoryIntakeStore  # noqa: E402
from agents.sim_director import build_sim_service  # noqa: E402
from tools import intake_qwen_worker as worker  # noqa: E402

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PHOTO = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
QWEN_WALLET = {"category": "wallet", "colors": ["black"], "shape": "rectangular", "materials": ["leather"],
               "logos_or_text": [], "sticker_status": "absent", "stickers": [], "distinctive_features": []}
QWEN_UNKNOWN = {**QWEN_WALLET, "category": "unknown", "colors": []}


class PendingPhotosTest(unittest.TestCase):
    def test_memory_store_lists_only_unanalyzed_photos(self):
        st = MemoryIntakeStore()
        a = st.create({"machine_id": "KIOSK-A", "place_id": None, "place_text": "해운대역 승강장", "finder": None,
                       "photo_path": "photos/KIOSK-A/a.jpg"})
        st.create({"machine_id": "KIOSK-A", "place_id": None, "place_text": "화장실", "finder": None, "photo_path": None})
        self.assertEqual([r["item_id"] for r in st.pending_photos()], [a["item_id"]])   # 사진 없는 물건은 제외
        self.assertEqual(set(st.pending_photos()[0]), {"item_id", "machine_id", "photo_path", "received_at"})  # 연락처·특징 없음
        from agents.intake import parse_features
        st.set_features(a["item_id"], parse_features({"qwen": QWEN_WALLET}))
        self.assertEqual(st.pending_photos(), [])

    def test_photo_path_must_stay_inside_photo_folder(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "photos").mkdir()
            (root / "photos" / "x.jpg").write_bytes(JPEG)
            self.assertEqual(worker.resolve_photo("photos/x.jpg", root), (root / "photos" / "x.jpg").resolve())
            with self.assertRaises(ValueError):
                worker.resolve_photo("../secret.txt", root)
            with self.assertRaises(FileNotFoundError):
                worker.resolve_photo("photos/none.jpg", root)


class FakeTower:
    def __init__(self, rows):
        self.rows, self.sent = rows, []

    def pending(self, limit=5):
        return [r for r in self.rows if r["item_id"] not in {s[0] for s in self.sent}]

    def send(self, iid, feats):
        self.sent.append((iid, feats))


class ProcessOnceTest(unittest.TestCase):
    def test_sends_features_and_gives_up_after_two_failures(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "ok.jpg").write_bytes(JPEG)
            t = FakeTower([{"item_id": "A-20261107-0001", "photo_path": "ok.jpg"},
                           {"item_id": "A-20261107-0002", "photo_path": "missing.jpg"}])
            tries, logs = {}, []
            self.assertEqual(worker.process_once(t, lambda p: QWEN_WALLET, tries, logs.append, root), 1)
            self.assertEqual(t.sent, [("A-20261107-0001", QWEN_WALLET)])
            worker.process_once(t, lambda p: QWEN_WALLET, tries, logs.append, root)
            worker.process_once(t, lambda p: QWEN_WALLET, tries, logs.append, root)   # 3번째는 건너뜀
            self.assertEqual(tries["A-20261107-0002"], 2)
            self.assertEqual(sum("실패" in m for m in logs), 2)

            def boom(p):
                raise RuntimeError("CUDA out of memory")
            t2 = FakeTower([{"item_id": "A-20261107-0003", "photo_path": "ok.jpg"}])
            self.assertEqual(worker.process_once(t2, boom, {}, logs.append, root), 0)   # 모델 오류도 작업자를 멈추지 않음


class SimKioskFlowTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.svc = build_sim_service({"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SIM_QWEN_WAIT": "0.5"})
        self.svc.photo_dir = self.tmp.name
        self.c = TestClient(build_app(self.svc))

    def intake(self):
        r = self.c.post("/api/kiosk/items", json={"machine_id": "KIOSK-A", "place_text": "해운대역 승강장", "photo": PHOTO})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["item_id"]

    def story(self, iid):
        return next(s for s in self.svc.board.stories.values() if (s.get("ids") or {}).get("item_id") == iid)

    def test_photo_intake_waits_for_qwen_then_collects_and_stores(self):
        iid = self.intake()
        pend = self.c.get("/api/admin/intake/pending-photos").json()
        self.assertEqual([p["item_id"] for p in pend], [iid])
        self.assertTrue((Path(self.tmp.name) / pend[0]["photo_path"]).is_file())
        r = self.c.post(f"/api/kiosk/items/{iid}/features", json={"qwen": QWEN_WALLET, "confidence": 0.85})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.svc.sim.wait_idle())
        st = self.story(iid)
        self.assertTrue(st["result"]["ok"], st["result"])
        self.assertEqual(self.svc.world.items[iid]["status"], "본센터 보관")
        self.assertEqual(self.svc.world.items[iid]["qwen"], QWEN_WALLET)          # 가상 탑뷰가 다시 찍을 때 쓰는 원본
        self.assertEqual(self.c.get("/api/admin/intake/pending-photos").json(), [])

    def test_no_worker_times_out_without_fake_features(self):
        iid = self.intake()
        self.assertTrue(self.svc.sim.wait_idle(5))
        st = self.story(iid)
        self.assertFalse(st["result"]["ok"])
        self.assertIn("사진 분석", st["result"]["text"])
        self.assertEqual(self.svc.world.items[iid]["status"], "등록기계 보관")       # 가짜 특징으로 진행하지 않음
        self.assertEqual(self.svc.world.items[iid]["category"], "확인 불가")

    def test_unknown_category_asks_staff(self):
        iid = self.intake()
        self.c.post(f"/api/kiosk/items/{iid}/features", json={"qwen": QWEN_UNKNOWN})
        self.assertTrue(self.svc.sim.wait_idle(5))
        self.assertIn("종류 확인 불가", self.story(iid)["result"]["text"])

    def test_pending_list_needs_admin_when_login_is_on(self):
        from fastapi.testclient import TestClient
        from agents.admin_auth import AdminAuth
        from agents.api import build_app
        c = TestClient(build_app(self.svc, admin_auth=AdminAuth("pw-for-test", "secret-for-test", "key-for-test")))
        self.assertEqual(c.get("/api/admin/intake/pending-photos").status_code, 401)
        self.assertEqual(c.get("/api/admin/intake/pending-photos", headers={"x-admin-key": "key-for-test"}).status_code, 200)

    def test_text_intake_without_photo_does_not_start_story(self):
        before = len(self.svc.board.stories)
        self.c.post("/api/kiosk/items", json={"machine_id": "KIOSK-A", "place_text": "해운대역 승강장"})
        self.assertEqual(len(self.svc.board.stories), before)

    def test_reset_stops_waiting_story(self):
        iid = self.intake()
        self.svc.sim.reset()
        self.assertTrue(self.svc.sim.wait_idle(5))
        self.assertIn("초기화", self.story(iid)["result"]["text"])


if __name__ == "__main__":
    unittest.main()
