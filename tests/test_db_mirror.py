"""11/10 가상 시연 기록을 팀 DB 에도 함께 저장(agents/db_mirror.py) 시험

확인하는 것
- 쓰기 하나하나가 맞는 SQL·값으로 나가는지(가짜 DB), 팀 DB 의 실제 기록·직원이 넣은 칸은 건드리지 않는지
- 팀 DB 가 꺼져 있어도 가상 시연은 끝까지 도는지(실패는 세기만), 접속 주소가 어디에도 찍히지 않는지
- 가상 시연 한 바퀴(키오스크 접수 → 특징 → 회수·보관 → 분실 신고 → 키오스크 회수)가 팀 DB 에 그대로 남는지
- 관제탑을 켤 때(TOWER_SIM_DB=1)만 붙고, 시험·다른 도구에서는 저절로 붙지 않는지
- 진짜 PostgreSQL 시험은 환경값 LF_TEST_DATABASE_URL(팀 DB 와 같은 표가 있는 시험용 DB)이 있을 때만 돈다
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents import db_mirror as dm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENV = {"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0.01", "TOWER_AGENT_TALK": "1"}
DSN = "postgresql://user:secret-pw@127.0.0.1:5434/lostfound"
ID_MASKED = "******-1******"
PHONE = "010-1234-5678"


class OperationalError(Exception):
    pass


class FakeDb:
    """psycopg 흉내: 실행한 SQL 과 값을 기록하고, SQL 종류마다 정해 둔 답을 돌려준다"""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.down = False                  # True 면 접속할 때 OperationalError
        self.connects = 0
        self.real_items: set[str] = set()   # 팀 DB 에 이미 있는 '실제 기록'의 접수 번호(가상 표시 없음)
        self.staff_slots: dict[str, str] = {}   # 직원이 넣어 둔 칸 → 물건
        self.max_item, self.max_claim = 0, 0
        self.rowcount = 1

    def connect(self, dsn):
        self.connects += 1
        if self.down:
            raise OperationalError("connection refused")
        return _Conn(self)

    def sqls(self, needle: str) -> list[tuple]:
        return [args for sql, args in self.calls if needle in sql]


class _Conn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return _Cur(self.db)


class _Cur:
    def __init__(self, db):
        self.db, self.last, self.args, self.rowcount = db, "", (), 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, args=()):
        self.db.calls.append((sql, tuple(args or ())))
        self.last, self.args, self.rowcount = sql, tuple(args or ()), self.db.rowcount
        return self

    def fetchone(self):
        sql, a, db = self.last, self.args, self.db
        if sql == dm.SQL_ITEM_UPSERT:
            return None if a[0] in db.real_items else (True,)
        if sql in (dm.SQL_CLAIM, dm.SQL_CASE):
            return (a[0],)
        if sql == dm.SQL_SLOT_ASSIGN:
            return None if a[0] in db.staff_slots else (a[0],)
        if sql == dm.SQL_SLOT_NOW:
            return (db.staff_slots[a[0]],) if a[0] in db.staff_slots else None
        if sql == dm.SQL_MAX_ITEM:
            return (db.max_item,)
        if sql == dm.SQL_MAX_CLAIM:
            return (db.max_claim,)
        return None


def mirror(db=None):
    db = db or FakeDb()
    return dm.DbMirror(DSN, connect=db.connect), db


ROW = {"item_id": "A-20261110-0001", "machine_id": "KIOSK-A", "place_text": "해운대역 승강장", "photo_path": "photos/a.jpg",
       "status": "등록기계 보관", "category": "확인 불가", "features": {}, "private_features": {}}


class WritesTest(unittest.TestCase):
    def test_new_item_writes_contact_and_first_log(self):
        m, db = mirror()
        m.item_new(ROW, {"name": "김습득", "phone": PHONE}, mark=None)
        self.assertTrue(m.wait())
        args = db.sqls("INSERT INTO item (")[0]
        self.assertEqual(args[:5], ("A-20261110-0001", "KIOSK-A", "해운대역 승강장", "photos/a.jpg", "등록기계 보관"))
        self.assertIsNone(args[8])                                       # 키오스크 사진 접수 = 진짜 접수(가상 표시 없음)
        self.assertEqual(db.sqls("INSERT INTO finder_contact")[0], ("A-20261110-0001", "김습득", PHONE))
        self.assertEqual(db.sqls("INSERT INTO item_status_log")[0], ("A-20261110-0001", None, "등록기계 보관", "kiosk"))
        self.assertEqual((m.ok, m.fail, m.skipped), (1, 0, 0))

    def test_virtual_item_is_marked(self):
        m, db = mirror()
        m.item_new({**ROW, "photo_path": None})
        m.wait()
        self.assertEqual(db.sqls("INSERT INTO item (")[0][8], dm.SIM_MARK)
        self.assertIn("WHERE item.object_id LIKE 'SIM%%'", dm.SQL_ITEM_UPSERT)   # 가상 표시가 있는 행만 다시 쓴다

    def test_real_record_with_same_number_is_left_alone(self):
        m, db = mirror()
        db.real_items.add("A-20261110-0001")
        m.item_new(ROW)
        m.item_status("A-20261110-0001", "등록기계 보관", "회수 중", "staff")
        m.item_features("A-20261110-0001", "지갑", {"color": "검정"}, {})
        m.slot_assign("R2-1", "A-20261110-0001")
        m.claim_new({"claim_id": "C-20261110-0001", "item_id": "A-20261110-0001", "quiz": []})
        m.wait()
        self.assertEqual(len(db.calls), 1)                                # 처음 한 번 물어본 것 말고는 아무것도 쓰지 않음
        self.assertEqual((m.ok, m.fail, m.skipped), (0, 0, 5))

    def test_status_writes_log_and_maps_writer(self):
        m, db = mirror()
        m.item_status("A-1", "등록기계 보관", "회수 중", "sim")
        m.wait()
        self.assertEqual(db.sqls("UPDATE item SET status")[0], ("회수 중", "A-1", "회수 중"))
        self.assertEqual(db.sqls("INSERT INTO item_status_log")[0], ("A-1", "등록기계 보관", "회수 중", "system"))
        db.calls.clear()
        db.rowcount = 0                                                   # 이미 그 상태 → 기록을 한 줄 더 만들지 않는다
        m.item_status("A-1", "회수 중", "회수 중", "tower")
        m.wait()
        self.assertEqual(db.sqls("INSERT INTO item_status_log"), [])

    def test_claim_filters_columns_db_would_reject(self):
        m, db = mirror()
        m.claim_new({"claim_id": "C-20261110-0001", "item_id": "A-1", "name_masked": "변*원", "id_no_masked": ID_MASKED,
                     "id_verified": True, "description": {"category": "지갑", "color": "검정", "place": "해운대"},
                     "quiz": [{"field": "place", "passed": True}, {"field": "weird", "passed": True}], "visit_date": "2026-11-10"})
        m.wait()
        claim = db.sqls("INSERT INTO claim (")[0]
        self.assertEqual(claim[:4], ("C-20261110-0001", "변*원", ID_MASKED, True))
        self.assertEqual(claim[4], '{"category": "지갑", "color": "검정"}')   # claim.description 은 정해진 칸만 받는다
        self.assertEqual(db.sqls("INSERT INTO quiz_attempt"), [("C-20261110-0001", "A-1", "place", True)])
        self.assertEqual(db.sqls("INSERT INTO reservation")[0], ("C-20261110-0001", "A-1", "2026-11-10"))

    def test_slot_rules(self):
        m, db = mirror()
        m.slot_assign("S-3", "A-1")                                       # 직원 보관 선반 자리는 없으면 만든다
        m.wait()
        self.assertEqual(db.sqls("INSERT INTO storage_slot")[0], ("S-3", "S", 3, "S"))
        self.assertEqual(db.sqls("INSERT INTO storage_assignment")[0], ("S-3", "A-1"))
        for sql in (dm.SQL_SLOT_MOVE_OUT, dm.SQL_SLOT_CLEAR_OLD, dm.SQL_SLOT_RELEASE):
            self.assertIn("assigned_by = 'system'", sql)                  # 이 부품이 쓴 칸만 비운다
        db.staff_slots["R4-1"] = "A-W01"                                  # 직원이 다른 물건을 넣어 둔 칸
        m.slot_assign("R4-1", "A-2")
        m.wait()
        self.assertEqual(m.skipped, 1)
        db.staff_slots["R1-1"] = "A-9"                                    # 이미 같은 물건이 있는 칸은 '된 것'
        m.slot_assign("R1-1", "A-9")
        m.wait()
        self.assertEqual((m.ok, m.skipped), (2, 1))

    def test_return_case_and_steps(self):
        m, db = mirror()
        m.return_case("A-1", {"case_id": "R-C-1", "claim_id": "C-1", "decision": "returned", "reason": "전달 완료",
                              "approved": True, "matched_object": "A-1", "seconds": 1.5, "steps": ["탑뷰 촬영", "매칭 완료"]})
        m.wait()
        self.assertEqual(db.sqls("INSERT INTO return_case")[0], ("R-C-1", "A-1", "C-1", "returned", "전달 완료", True, "A-1", 1.5))
        self.assertEqual(db.sqls("INSERT INTO return_step"), [("R-C-1", "탑뷰 촬영"), ("R-C-1", "매칭 완료")])


class DownTest(unittest.TestCase):
    def test_db_down_counts_and_rests(self):
        m, db = mirror()
        db.down = True
        for i in range(6):
            m.item_status(f"A-{i}", "a", "b")
        m.wait()
        st = m.stats()
        self.assertEqual((st["ok"], st["fail"], st["connected"], st["resting"]), (0, 6, False, True))
        self.assertEqual(db.connects, 2)                                  # 두 번 안 되면 쉬는 동안 더 두드리지 않는다
        self.assertEqual(st["last_error"], "item 상태: OperationalError")
        self.assertNotIn("secret-pw", repr(m) + str(st))                   # 접속 주소·비밀번호는 어디에도 없다

    def test_sync_numbers(self):
        from agents.claims import MemoryClaimStore
        from agents.sim_world import SimWorld
        from datetime import date
        m, db = mirror()
        db.max_item, db.max_claim = 7, 4
        w, claims, day = SimWorld(seed=False), MemoryClaimStore(), date(2026, 11, 10)
        self.assertTrue(m.sync_numbers(w, claims, day))
        self.assertEqual(w._seq["A-20261110-"], 7)
        self.assertEqual(claims.seq_floor["20261110"], 4)
        row = w.create({"machine_id": "KIOSK-A", "place_id": None, "place_text": "x", "finder": None, "photo_path": None}, today=day)
        self.assertEqual(row["item_id"], "A-20261110-0008")               # 팀 DB 의 다음 번호
        n = db.connects
        self.assertTrue(m.sync_numbers(w, claims, day))                   # 같은 날은 한 번만 읽는다
        self.assertEqual(db.connects, n)
        db.down = True
        self.assertFalse(m.sync_numbers(w, claims, date(2026, 11, 11)))
        self.assertFalse(m.sync_numbers(w, claims, date(2026, 11, 11)))   # 실패 뒤에는 잠깐 쉰다(접수를 늦추지 않게)
        self.assertEqual(db.connects, n + 1)

    def test_claim_numbers_follow_floor(self):
        from agents.claims import MemoryClaimStore
        from datetime import date
        s = MemoryClaimStore()
        s.seq_floor["20261110"] = 4
        c = {"item_id": "A-1", "name_masked": "변*원", "id_no_masked": ID_MASKED, "id_verified": True, "description": {},
             "quiz": [], "visit_date": "2026-11-10"}
        self.assertEqual(s.create(c, date(2026, 11, 10))["claim_id"], "C-20261110-0005")
        self.assertEqual(s.create(c, date(2026, 11, 10))["claim_id"], "C-20261110-0006")
        self.assertEqual(MemoryClaimStore().create(c, date(2026, 11, 10))["claim_id"], "C-20261110-0001")   # 예전 그대로


class AttachTest(unittest.TestCase):
    def build(self, db=None):
        from agents.sim_director import build_sim_service
        svc = build_sim_service(ENV)
        m, db = mirror(db)
        dm.attach(svc, m)
        return svc, m, db

    def round(self, svc):
        """관제탑 API 로 한 바퀴: 키오스크 사진 접수 → 사진 분석 결과 → 회수·보관 → 분실 신고 → 본센터 키오스크 회수"""
        import base64
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents import observability
        from agents.api import build_app
        c = TestClient(build_app(svc))
        self.addCleanup(observability.set_listener, "live-board", None)
        jpg = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(64) + b"\xff\xd9").decode()
        r = c.post("/api/kiosk/items", json={"machine_id": "KIOSK-A", "place_text": "해운대역 승강장", "photo": jpg,
                                             "finder": {"name": "김습득", "phone": PHONE}})
        self.assertEqual(r.status_code, 200, r.text)
        iid = r.json()["item_id"]
        r = c.post(f"/api/kiosk/items/{iid}/features", json={"qwen": {"category": "wallet", "colors": ["black"], "shape": "rectangular",
                                                                      "material": "leather", "visible_text": "VOVA"}, "confidence": 0.9})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(svc.sim.wait_idle(20))
        lost = c.post("/sim/lost", json={"text": "검정 지갑 잃어버렸어요, 해운대역", "visit": "kiosk", "name_masked": "변*원",
                                         "id_no_masked": ID_MASKED}).json()
        for _ in range(5):
            if not lost.get("pending_id"):
                break
            lost = c.post(f"/sim/lost/{lost['pending_id']}/answer", json={"text": "모름"}).json()
        self.assertTrue(lost.get("claim_id"), lost)
        out = c.post("/api/kiosk/returns", json={"machine_id": "CENTER", "claim_id": lost["claim_id"], "id_no_masked": ID_MASKED})
        self.assertEqual(out.status_code, 200, out.text)
        svc.sim.wait_idle(20)
        return iid, lost["claim_id"], out.json()

    def test_seed_items_are_synced_and_marked(self):
        svc, m, db = self.build()
        m.wait()
        seeds = db.sqls("INSERT INTO item (")
        self.assertEqual(len(seeds), len(svc.world.items))
        self.assertTrue(all(a[8] == dm.SIM_MARK and a[1] == "CENTER" for a in seeds))
        self.assertEqual(len(db.sqls("INSERT INTO storage_assignment")), len(seeds))
        self.assertEqual(db.sqls("INSERT INTO item_status_log"), [])       # 시연용 물건은 상태 기록을 꾸며 넣지 않는다
        self.assertIs(dm.attach(svc, m), m)                                # 두 번 붙여도 한 번

    def test_full_round_reaches_team_db(self):
        svc, m, db = self.build()
        m.wait()
        db.calls.clear()
        iid, cid, out = self.round(svc)
        self.assertEqual(out["decision"], "returned")
        self.assertTrue(m.wait())
        item = db.sqls("INSERT INTO item (")[0]
        self.assertEqual((item[0], item[1], item[2], item[8]), (iid, "KIOSK-A", "해운대역 승강장", None))
        self.assertTrue(item[3].startswith("photos/KIOSK-A/"))             # 사진 위치도 함께
        self.assertEqual(db.sqls("INSERT INTO finder_contact")[0][0], iid)
        feats = db.sqls("UPDATE item SET category")[0]
        self.assertEqual((feats[0], feats[3]), ("지갑", iid))
        import json
        pub, priv = json.loads(feats[1]), json.loads(feats[2])
        self.assertEqual(pub["color"], "검정")
        self.assertFalse({"mark", "visible_text"} & set(pub))              # 공개 칸에는 비공개 특징이 없다(팀 DB 제약과 같음)
        self.assertTrue({"mark", "visible_text"} >= set(priv) and priv)
        moves = [a[0] for a in db.sqls("UPDATE item SET status") if a[1] == iid]
        self.assertEqual(moves[:2], ["회수 중", "본센터 보관"])
        self.assertIn("인계 대기", moves)
        self.assertTrue(any(a[1] == iid for a in db.sqls("INSERT INTO storage_assignment")))
        self.assertEqual(db.sqls("INSERT INTO claim (")[0][0], cid)
        self.assertEqual(db.sqls("INSERT INTO reservation")[0][:2], (cid, iid))
        self.assertEqual(db.sqls("UPDATE reservation SET status")[0], (cid,))
        case = db.sqls("INSERT INTO return_case")[0]
        self.assertEqual((case[1], case[2], case[3]), (iid, cid, "returned"))
        self.assertEqual((m.fail, m.skipped), (0, 0))

    def test_demo_keeps_running_when_team_db_is_down(self):
        db = FakeDb()
        db.down = True
        svc, m, db = self.build(db)
        iid, cid, out = self.round(svc)
        self.assertEqual(out["decision"], "returned")                      # 팀 DB 가 꺼져 있어도 시연은 끝까지
        m.wait()
        self.assertEqual(m.ok, 0)
        self.assertGreater(m.fail, 0)
        self.assertEqual(svc.get_claim(cid)["item_id"], iid)               # 읽기는 가상 세계에서

    def test_broken_mirror_never_breaks_store(self):
        svc, m, db = self.build()

        def boom(*a, **k):
            raise RuntimeError("부품 고장")
        m.item_new = m.item_status = m.claim_new = m.slot_assign = m.return_case = boom
        iid, cid, out = self.round(svc)
        self.assertEqual(out["decision"], "returned")

    def test_photo_path_from_world_and_mirror(self):
        from agents.sim_world import SimWorld
        w = SimWorld(seed=False)
        row = w.create({"machine_id": "KIOSK-A", "place_id": None, "place_text": "x", "finder": None, "photo_path": "photos/a.jpg"})
        self.assertEqual(w.photo_path(row["item_id"]), "photos/a.jpg")
        self.assertIsNone(w.photo_path("A-20000101-0001"))


class WiringTest(unittest.TestCase):
    def test_from_env_needs_switch_and_url(self):
        self.assertIsNone(dm.from_env({}))
        self.assertIsNone(dm.from_env({"TOWER_SIM_DB": "1"}))
        self.assertIsNone(dm.from_env({"DATABASE_URL": DSN}))
        self.assertIsNone(dm.from_env({"TOWER_SIM_DB": "0", "DATABASE_URL": DSN}))
        self.assertIsInstance(dm.from_env({"TOWER_SIM_DB": "1", "DATABASE_URL": DSN}), dm.DbMirror)

    def test_not_attached_unless_tower_start_asks(self):
        from agents.sim_director import build_sim_service
        self.assertIsNone(getattr(build_sim_service(ENV), "db_mirror", None))   # 시험·도구가 만든 가상 시연에는 붙지 않는다
        api = (ROOT / "agents" / "api.py").read_text(encoding="utf-8")
        self.assertIn("db_mirror.from_env()", api)

    def test_api_reports_off(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents import observability
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        c = TestClient(build_app(build_sim_service(ENV)))
        try:
            self.assertEqual(c.get("/api/admin/db/recent").json(), {"on": False})
            self.assertEqual(c.get("/api/admin/live/state?detail=1").json()["db_mirror"], {"on": False})
        finally:
            observability.set_listener("live-board", None)

    def test_api_reports_team_db_rows(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents import observability
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        svc = build_sim_service(ENV)
        m, db = mirror()
        dm.attach(svc, m)
        m.recent = lambda limit=8: {"items": [{"item_id": "A-1", "station": "해운대"}], "counts": {"item": 1}}
        c = TestClient(build_app(svc))
        try:
            d = c.get("/api/admin/db/recent?limit=3").json()
            self.assertEqual((d["on"], d["items"][0]["station"], d["counts"]["item"]), (True, "해운대", 1))
            self.assertTrue(c.get("/api/admin/live/state?detail=1").json()["db_mirror"]["on"])
            m.recent = lambda limit=8: (_ for _ in ()).throw(OperationalError(DSN))
            bad = c.get("/api/admin/db/recent")
            self.assertEqual(bad.json()["error"], "OperationalError")
            self.assertNotIn("secret-pw", bad.text)                        # 오류에도 접속 주소가 실리지 않는다
        finally:
            observability.set_listener("live-board", None)

    def test_start_script_turns_it_on(self):
        bat = (ROOT / "tools" / "start_tower.bat").read_bytes()
        self.assertIn(b"set TOWER_SIM_DB=1\r\n", bat)
        self.assertIn(b'if /i "%%a"=="nodb" set TOWER_SIM_DB=0\r\n', bat)
        line = next(x for x in bat.split(b"\r\n") if b"set TOWER_SIM_DB=1" in x)
        self.assertTrue(all(c < 128 for c in line))


@unittest.skipUnless(os.environ.get("LF_TEST_DATABASE_URL"), "LF_TEST_DATABASE_URL(시험용 PostgreSQL)이 있을 때만")
class RealPostgresTest(unittest.TestCase):
    """진짜 PostgreSQL(팀 DB 와 같은 표: center/schema.sql + migrations). 시험이 넣은 행은 끝나고 지운다"""

    def setUp(self):
        import psycopg
        self.dsn = os.environ["LF_TEST_DATABASE_URL"]
        self.pg = psycopg.connect(self.dsn, autocommit=True)
        self.clean()

    def tearDown(self):
        self.clean()
        self.pg.close()

    def clean(self):
        with self.pg.cursor() as cur:
            cur.execute("TRUNCATE return_step, return_case, reservation, quiz_attempt, claim_candidate, claim, storage_assignment, "
                        "finder_contact, item_status_log, inventory_check, collection_item, item CASCADE")

    def q(self, sql, *args):
        with self.pg.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()

    def test_round_and_protection(self):
        from agents.sim_director import build_sim_service
        # 팀 DB 에 먼저 있던 실제 기록: 오늘 본센터 접수 0002 번(가상 표시 없음) + 직원이 넣은 칸
        from datetime import date
        real = f"H-{date.today():%Y%m%d}-0002"
        self.q("INSERT INTO item (item_id, machine_id, place_text, status, category) VALUES (%s, 'CENTER', '실제 접수', '인계 완료', '지갑') RETURNING 1", real)
        self.q("INSERT INTO item (item_id, machine_id, place_text, status, category) VALUES ('A-W01', 'KIOSK-A', 'x', '본센터 보관', '지갑') RETURNING 1")
        self.q("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES ('R4-1', 'A-W01', 'staff') RETURNING 1")
        svc = build_sim_service(ENV)
        m = dm.DbMirror(self.dsn)
        dm.attach(svc, m)
        iid, cid, out = AttachTest.round(self, svc)
        self.assertTrue(m.wait(20))
        self.assertEqual(out["decision"], "returned")
        self.assertEqual(m.stats()["fail"], 0, m.stats())
        self.assertEqual(self.q("SELECT place_text, status FROM item WHERE item_id = %s", real), [("실제 접수", "인계 완료")])
        self.assertEqual(self.q("SELECT item_id, assigned_by FROM storage_assignment WHERE slot_id = 'R4-1'"), [("A-W01", "staff")])
        row = self.q("SELECT machine_id, place_text, status, category, photo_path IS NOT NULL, object_id FROM item WHERE item_id = %s", iid)
        self.assertEqual(row, [("KIOSK-A", "해운대역 승강장", "인계 대기", "지갑", True, None)])
        self.assertEqual(self.q("SELECT count(*) FROM finder_contact WHERE item_id = %s", iid), [(1,)])
        logs = [r[0] for r in self.q("SELECT to_status FROM item_status_log WHERE item_id = %s ORDER BY id", iid)]
        self.assertEqual(logs[:3], ["등록기계 보관", "회수 중", "본센터 보관"])
        self.assertEqual(logs[-1], "인계 대기")
        self.assertEqual(self.q("SELECT item_id, status FROM reservation WHERE claim_id = %s", cid), [(iid, "visited")])
        self.assertEqual(self.q("SELECT decision, approved FROM return_case WHERE claim_id = %s", cid), [("returned", True)])
        seeds = self.q("SELECT count(*) FROM item WHERE object_id = 'SIM'")[0][0]
        # 11/10: 실제 기록과 번호가 겹치면 가상 물건이 새 번호를 받는다(전에는 겹친 1개가 저장되지 않고 가상 찾기 요청이 진짜 물건에 걸릴 수 있었다)
        self.assertEqual(seeds, len(svc.world.items) - 1)                  # 키오스크 접수 1개(진짜 접수라 가상 표시 없음) 빼고
        self.assertNotIn(real, svc.world.items)
        d = m.recent(3)
        self.assertEqual((d["items"][0]["item_id"], d["items"][0]["station"], d["items"][0]["has_photo"]), (iid, "해운대", True))
        # 다시 켜면: 번호가 이어지고(겹치지 않음) 시연용 물건은 다시 채워진다
        svc2 = build_sim_service(ENV)
        m2 = dm.DbMirror(self.dsn)
        dm.attach(svc2, m2)
        rec = svc2.create_item({"machine_id": "KIOSK-A", "place_text": "대합실·개찰구 주변"})
        self.assertTrue(m2.wait(20))
        self.assertNotEqual(rec["item_id"], iid)
        self.assertEqual(m2.stats()["fail"], 0, m2.stats())
        self.assertEqual(self.q("SELECT status FROM item WHERE item_id = %s", iid), [("인계 대기",)])   # 앞선 기록은 그대로 남는다

    def test_first_item_number_clash_with_real_intake(self):
        """11/10 처음 물건(해운대역 A-…-0001)과 그날 먼저 들어온 진짜 키오스크 접수 번호가 겹칠 때:
        가상 물건은 새 번호를 받고(진짜 기록은 그대로), 다시 켜면 그 번호를 다시 쓴다(가상 물건이 켤 때마다 늘지 않음)"""
        from datetime import date
        from agents.sim_director import build_sim_service
        day = f"{date.today():%Y%m%d}"
        for n in (1, 2, 3):
            self.q("INSERT INTO item (item_id, machine_id, place_text, status, category) VALUES (%s, 'KIOSK-A', '진짜 접수', '등록기계 보관', '핸드크림') RETURNING 1",
                   f"A-{day}-000{n}")
        env = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}
        svc = build_sim_service(env)
        m = dm.DbMirror(self.dsn)
        dm.attach(svc, m)
        self.assertTrue(m.wait(20))
        seed = f"A-{day}-0004"
        self.assertEqual(list(svc.world.items), [seed])
        self.assertEqual(svc.world.slot_id_of(seed), "R3-1")
        self.assertEqual(self.q("SELECT place_text, object_id FROM item WHERE item_id = %s", f"A-{day}-0001"), [("진짜 접수", None)])
        r = svc.sim.lost("해운대역에서 분홍 핸드크림 잃어버렸어요", {"visit": "kiosk", "name_masked": "홍*동", "id_no_masked": "******-1******"})
        self.assertTrue(svc.sim.wait_idle())
        self.assertTrue(m.wait(20))
        self.assertEqual(self.q("SELECT item_id FROM reservation WHERE claim_id = %s", r["claim_id"]), [(seed,)])   # 진짜 물건에 걸리지 않음
        svc.sim.cancel_claim(r["claim_id"], by_staff=True)
        self.assertTrue(m.wait(20))
        self.assertEqual(self.q("SELECT status FROM reservation WHERE claim_id = %s", r["claim_id"]), [("cancelled",)])
        svc2 = build_sim_service(env)                                       # 다시 켜기
        m2 = dm.DbMirror(self.dsn)
        dm.attach(svc2, m2)
        self.assertTrue(m2.wait(20))
        self.assertEqual(list(svc2.world.items), [seed])
        self.assertEqual(self.q("SELECT count(*) FROM item")[0][0], 4)
        nxt = svc2.create_item({"machine_id": "KIOSK-A", "place_text": "대합실·개찰구 주변"})
        self.assertEqual(nxt["item_id"], f"A-{day}-0005")                   # 다음 접수는 가장 큰 번호 다음
        self.assertEqual(m2.stats()["fail"], 0, m2.stats())


if __name__ == "__main__":
    unittest.main()
