"""11/10 물건 기록 전체 삭제(로봇 작업대 화면의 [기록 삭제]) 시험

확인하는 것
- 보관 칸에 든 물건을 지우면 물건·칸 기록이 없어지고 칸이 빈다
- 찾기 요청·반환 기록이 걸린 물건도 함께 지운다(찌꺼기 없음), 다른 물건의 기록은 그대로
- 없는 번호 404, 형식 오류 422
- 팀 DB 복제에 전체 삭제가 전달되고, 진짜 PostgreSQL 에서 딸린 행이 하나도 남지 않는다(LF_TEST_DATABASE_URL 이 있을 때)
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import observability  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class PurgeApiTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        self.svc = build_sim_service({"TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "0"})
        self.c = TestClient(build_app(self.svc))
        self.addCleanup(observability.set_listener, "live-board", None)
        self.w = self.svc.world

    def stored(self):
        return sorted(i for i, r in self.w.items.items() if r["loc"] == "bin")

    def slots(self):
        return {s["slot_id"]: s.get("item_id") for s in self.c.get("/api/admin/storage/robot-targets").json()["slots"]}

    def test_purge_stored_item_frees_slot(self):
        iid = self.stored()[0]
        slot = self.w.slot_id_of(iid)
        self.assertEqual(self.slots()[slot], iid)
        others = set(self.w.items) - {iid}
        r = self.c.post(f"/api/admin/items/{iid}/purge")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["slot"], slot)
        self.assertNotIn(iid, self.w.items)
        self.assertEqual(set(self.w.items), others)                     # 다른 물건은 그대로
        self.assertIsNone(self.slots()[slot])                           # 칸이 비었다(보관함 정답지도)
        self.assertEqual(self.c.get(f"/api/admin/storage/robot-target/{iid}").json().get("ok"), False)
        evs = self.c.get("/api/admin/live/state?after=0&detail=1").json()["events"]
        dels = [e["db"] for e in evs if e["channel"] == "db" and e["db"]["op"] == "DELETE"]
        self.assertIn(("item", iid), [(d["table"], d["key"]) for d in dels])
        self.assertEqual(self.c.post(f"/api/admin/items/{iid}/purge").status_code, 404)
        self.assertEqual(self.c.post("/api/admin/items/나쁜번호/purge").status_code, 422)

    def test_purge_removes_claims_and_return_records(self):
        iid, other = self.stored()[0], self.stored()[1]
        mine = self.svc.claims.create({"item_id": iid, "name_masked": "변*원", "id_no_masked": "******-1******", "description": {}, "quiz": []})
        keep = self.svc.claims.create({"item_id": other, "name_masked": "김*수", "id_no_masked": "******-2******", "description": {}, "quiz": []})
        self.svc.recorder._rows["RC-TEST-1"] = {"case_id": "RC-TEST-1", "item_id": iid, "decision": "rejected", "steps": []}
        self.svc.recorder._rows["RC-TEST-2"] = {"case_id": "RC-TEST-2", "item_id": other, "decision": "rejected", "steps": []}
        self.assertEqual(self.svc.claims.active_for_item(iid), mine["claim_id"])
        r = self.c.post(f"/api/admin/items/{iid}/purge")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["claims"], [mine["claim_id"]])
        self.assertEqual(r.json()["cases"], ["RC-TEST-1"])
        self.assertNotIn(iid, self.w.items)
        self.assertIsNone(self.svc.claims.get(mine["claim_id"]))                  # 찾기 요청 찌꺼기 없음
        self.assertIsNone(self.svc.claims.active_for_item(iid))
        self.assertFalse(self.svc.recorder.has("RC-TEST-1"))                      # 반환 기록 찌꺼기 없음
        self.assertIsNotNone(self.svc.claims.get(keep["claim_id"]))               # 다른 물건의 기록은 그대로
        self.assertTrue(self.svc.recorder.has("RC-TEST-2"))
        self.assertIn(other, self.w.items)
        self.assertEqual(self.c.get(f"/claims/{mine['claim_id']}").status_code, 404)

    def test_busy_item_is_refused(self):
        iid = self.stored()[0]
        self.w.items[iid]["status"] = "반환 중"                                    # 로봇이 움직이는 중
        r = self.c.post(f"/api/admin/items/{iid}/purge")
        self.assertEqual(r.status_code, 409)
        self.assertIn(iid, self.w.items)

    def test_live_page_has_purge_ui(self):
        html = (ROOT / "web" / "live" / "index.html").read_text(encoding="utf-8")
        for needle in ('id="purgeList"', "/api/admin/items/${encodeURIComponent(id)}/purge", "한 번 더 → 삭제", "되돌릴 수 없어요"):
            self.assertIn(needle, html)


class MirrorPurgeTest(unittest.TestCase):
    def test_world_purge_reaches_mirror(self):
        from agents import db_mirror
        from agents.sim_director import build_sim_service
        svc = build_sim_service({"TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "0"})
        calls = []

        class M:
            def __getattr__(self, name):
                return lambda *a, **k: calls.append((name, a))
        db_mirror.attach(svc, M())
        iid = next(i for i, r in svc.world.items.items() if r["loc"] == "bin")
        self.assertTrue(svc.sim.purge_item(iid)["ok"])
        self.assertIn(("item_purge", (iid,)), calls)

    @unittest.skipUnless(os.environ.get("LF_TEST_DATABASE_URL"), "진짜 PostgreSQL 시험은 LF_TEST_DATABASE_URL 이 있을 때만")
    def test_real_db_leaves_no_rows(self):
        import psycopg
        from agents.db_mirror import DbMirror
        dsn = os.environ["LF_TEST_DATABASE_URL"]
        a, b, cid, cid2, case = "Z-20990101-0021", "Z-20990101-0022", "C-20990101-0021", "C-20990101-0022", "RC-20990101-0021"
        tables = ("return_step", "return_case", "quiz_attempt", "reservation", "claim_candidate", "claim", "storage_assignment",
                  "inventory_check", "finder_contact", "item_status_log", "item")

        def clean(cur):
            cur.execute("DELETE FROM return_step WHERE case_id = %s", (case,))
            cur.execute("DELETE FROM return_case WHERE case_id = %s", (case,))
            for t in ("quiz_attempt", "reservation", "claim_candidate"):
                cur.execute(f"DELETE FROM {t} WHERE claim_id = ANY(%s)", ([cid, cid2],))
            cur.execute("DELETE FROM claim WHERE claim_id = ANY(%s)", ([cid, cid2],))
            for t in ("storage_assignment", "inventory_check", "finder_contact", "item_status_log", "item"):
                cur.execute(f"DELETE FROM {t} WHERE item_id = ANY(%s)", ([a, b],))
        with psycopg.connect(dsn) as c, c.cursor() as cur:
            clean(cur)
            cur.execute("SELECT machine_id FROM machine ORDER BY 1 LIMIT 1")
            mach = cur.fetchone()[0]
            for i in (a, b):
                cur.execute("INSERT INTO item (item_id, machine_id, place_text, status, category) VALUES (%s,%s,'시험','본센터 보관','지갑')", (i, mach))
                cur.execute("INSERT INTO item_status_log (item_id, to_status, changed_by) VALUES (%s,'본센터 보관','staff')", (i,))
            cur.execute("INSERT INTO finder_contact (item_id, name, phone) VALUES (%s,'시험','010-0000-0000')", (a,))
            cur.execute("SELECT slot_id, section_code FROM storage_slot s WHERE NOT EXISTS (SELECT 1 FROM storage_assignment x WHERE x.slot_id = s.slot_id) ORDER BY 1 LIMIT 1")
            slot, section = cur.fetchone()
            cur.execute("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES (%s,%s,'system')", (slot, a))
            cur.execute("INSERT INTO inventory_check (section_code, item_id, expected_count, status) VALUES (%s,%s,1,'count_match')", (section, a))
            for k in (cid, cid2):
                cur.execute("INSERT INTO claim (claim_id, consented_at, name_masked, id_no_masked, id_verified, description) VALUES (%s, now(), '시*', '******-1******', false, '{}'::jsonb)", (k,))
            cur.execute("INSERT INTO claim_candidate (claim_id, item_id, rank, score) VALUES (%s,%s,1,0.9)", (cid, a))
            cur.execute("INSERT INTO quiz_attempt (claim_id, item_id, field, passed) VALUES (%s,%s,'color',true)", (cid, a))
            cur.execute("INSERT INTO reservation (claim_id, item_id, visit_date) VALUES (%s,%s,current_date)", (cid, a))
            cur.execute("INSERT INTO claim_candidate (claim_id, item_id, rank, score) VALUES (%s,%s,1,0.8), (%s,%s,2,0.7)", (cid2, a, cid2, b))   # 두 물건을 후보로 둔 요청
            cur.execute("INSERT INTO return_case (case_id, item_id, claim_id, decision, reason) VALUES (%s,%s,%s,'returned','시험')", (case, a, cid))
            cur.execute("INSERT INTO return_step (case_id, step) VALUES (%s,'locate')", (case,))
        m = DbMirror(dsn)
        m.item_purge(a)
        m.wait()
        try:
            with psycopg.connect(dsn) as c, c.cursor() as cur:
                left = {}
                for t in ("return_case", "quiz_attempt", "reservation", "claim_candidate", "storage_assignment", "inventory_check",
                          "finder_contact", "item_status_log", "item"):
                    cur.execute(f"SELECT count(*) FROM {t} WHERE item_id = %s", (a,))
                    left[t] = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM return_step WHERE case_id = %s", (case,))
                left["return_step"] = cur.fetchone()[0]
                self.assertEqual(set(left.values()), {0}, left)                   # 그 물건의 행이 어느 표에도 없다
                cur.execute("SELECT claim_id FROM claim WHERE claim_id = ANY(%s) ORDER BY 1", ([cid, cid2],))
                self.assertEqual([r[0] for r in cur.fetchall()], [cid2])          # 그 물건만 가리키던 요청은 지워지고, 다른 후보가 남은 요청은 남는다
                cur.execute("SELECT count(*) FROM item WHERE item_id = %s", (b,))
                self.assertEqual(cur.fetchone()[0], 1)                            # 다른 물건은 그대로
                cur.execute("SELECT count(*) FROM storage_assignment WHERE slot_id = %s", (slot,))
                self.assertEqual(cur.fetchone()[0], 0)                            # 칸이 비었다
            self.assertEqual(m.stats()["fail"], 0)
        finally:
            with psycopg.connect(dsn) as c, c.cursor() as cur:
                clean(cur)
        self.assertEqual(len(tables), 11)


if __name__ == "__main__":
    unittest.main()
