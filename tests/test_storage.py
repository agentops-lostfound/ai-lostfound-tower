"""보관함 정답지(agents/storage.py · 007 마이그레이션 · tools/storage_export.py) 시험 — 11/6 LF-8"""
import io
import json
import os
import re
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from agents.storage import (LAYOUT, ON_SHELF, MemoryStorageStore, PostgresStorageStore, StorageConflict,
                            StorageError)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "center" / "migrations" / "007_storage_slots_1106.sql"


def gunte_load_storage(storage: dict):
    """김건태 run_storage_check.load_storage 와 같은 검사(LF-3-yolo-aruco 브랜치, 11/5) — 형식 호환 확인용 복사"""
    sections, inventory = storage["sections"], storage["inventory"]
    occupied = set()
    for item_id, location in inventory.items():
        section, slot = location["section"], location["slot"]
        pose = sections[section]["slots"][slot]
        if not item_id.strip() or not isinstance(pose, str) or not pose.strip():
            raise ValueError("Every stored item requires an ID and a named pose")
        if (section, slot) in occupied:
            raise ValueError(f"Multiple items assigned to section {section}, slot {slot}")
        occupied.add((section, slot))
    return sections, inventory


class Items:
    """item_lookup 가짜: 물건 번호 → 상태·품목"""

    def __init__(self):
        self.db = {"A-W01": {"status": "본센터 보관", "category": "지갑"},
                   "A-W02": {"status": "본센터 보관", "category": "지갑"},
                   "A-W03": {"status": "확인 중", "category": "모형폰"},
                   "A-W04": {"status": "등록기계 보관", "category": "USB"},
                   "A-W05": {"status": "승인·수령 예약", "category": "립밤"}}

    def __call__(self, item_id):
        return self.db.get(item_id)


class MemoryStorageTest(unittest.TestCase):
    def setUp(self):
        self.items = Items()
        self.s = MemoryStorageStore(item_lookup=self.items)

    def test_layout_is_4_rows_by_2_plus_handover(self):
        lay = self.s.layout()
        self.assertEqual([x["code"] for x in lay["sections"]], ["R1", "R2", "R3", "R4", "H"])
        self.assertEqual(lay["summary"], {"shelf_slots": 8, "used": 0, "free": 8, "slots_without_pose": 8})
        r1 = lay["sections"][0]
        self.assertEqual([x["slot_id"] for x in r1["slots"]], ["R1-1", "R1-2"])
        self.assertEqual({x["note"] for x in r1["slots"]}, {"사선 배치·간격 넓음"})      # 11/6: 폰은 사선, 간격 넓음
        self.assertEqual(lay["sections"][4]["kind"], "handover")

    def test_assign_conflict_move_and_release(self):
        r = self.s.assign("A-W01", "R4-1")
        self.assertEqual((r["section"], r["slot"], r["pose_name"]), ("R4", "1", None))
        with self.assertRaises(StorageConflict):                     # 칸 하나에 물건 하나
            self.s.assign("A-W02", "R4-1")
        self.s.assign("A-W01", "R4-2")                                # 같은 물건을 옮기면 예전 칸은 빔
        lay = {x["slot_id"]: x for sec in self.s.layout()["sections"] for x in sec["slots"]}
        self.assertIsNone(lay["R4-1"]["item"])
        self.assertEqual(lay["R4-2"]["item"]["item_id"], "A-W01")
        self.assertEqual(self.s.release(item_id="A-W01"), {"ok": True, "slot_id": "R4-2", "item_id": "A-W01"})
        self.assertEqual(self.s.release(slot_id="R4-2"), {"ok": True, "slot_id": "R4-2", "item_id": None})

    def test_rejects_wrong_category_handover_and_off_shelf_status(self):
        with self.assertRaises(StorageError):                         # 지갑을 모형폰 행에
            self.s.assign("A-W01", "R1-1")
        self.assertEqual(self.s.assign("A-W01", "R1-1", override_category=True)["slot_id"], "R1-1")
        with self.assertRaises(StorageError):                         # 인계 구역은 보관 칸이 아님
            self.s.assign("A-W02", "H-1", override_category=True)
        with self.assertRaises(StorageConflict):                      # 아직 등록기계에 있는 물건
            self.s.assign("A-W04", "R2-1")
        with self.assertRaises(StorageError) as cm:
            self.s.assign("A-W99", "R2-1")
        self.assertTrue(cm.exception.not_found)
        with self.assertRaises(StorageError) as cm:
            self.s.assign("A-W02", "R9-1")
        self.assertTrue(cm.exception.not_found)
        for bad in (("A W01", "R1-1"), ("A-W01", "R1_1"), (None, "R1-1")):
            with self.assertRaises(StorageError):
                self.s.assign(*bad)
        with self.assertRaises(StorageError):
            self.s.release()
        with self.assertRaises(StorageError):
            self.s.release(item_id="A-W01", slot_id="R1-1")

    def test_export_matches_gunte_format_and_warns_without_pose(self):
        self.s.assign("A-W03", "R1-2")
        self.s.assign("A-W05", "R3-1")
        out = self.s.export()
        self.assertEqual(out["inventory"], {"A-W03": {"section": "R1", "slot": "2"},
                                            "A-W05": {"section": "R3", "slot": "1"}})
        self.assertEqual(out["sections"]["R1"]["slots"], {"1": None, "2": None})
        self.assertEqual(len(out["warnings"]), 2)
        with self.assertRaises(ValueError):                           # 자세가 비면 비전 쪽도 거절(안전)
            gunte_load_storage(out)
        self.s.set_pose("R1-2", "pose_1")
        self.s.set_pose("R3-1", "shelf_r3_1")
        out = self.s.export()
        self.assertEqual(out["warnings"], [])
        sections, inventory = gunte_load_storage(json.loads(json.dumps(out)))
        loc = inventory["A-W03"]
        self.assertEqual(sections[loc["section"]]["slots"][loc["slot"]], "pose_1")
        self.assertNotIn("bounds_mm", out["sections"]["R1"])
        self.s.set_bounds("R1", [0, 0, 250, 60])
        self.assertEqual(self.s.export()["sections"]["R1"]["bounds_mm"], [0.0, 0.0, 250.0, 60.0])
        for bad in ([0, 0, 0, 60], [0, 0, 250], "x", [0, 0, True, 60]):
            with self.assertRaises(StorageError):
                self.s.set_bounds("R1", bad)

    def test_items_leaving_shelf(self):
        self.s.assign("A-W01", "R4-1")
        self.s.assign("A-W02", "R4-2")
        self.items.db["A-W01"]["status"] = "반환 중"                  # 로봇이 집는 중: 칸은 유지, 내보내기에서는 빠짐
        self.assertNotIn("A-W01", self.s.export()["inventory"])
        self.assertEqual(self.s.layout()["summary"]["used"], 2)
        self.items.db["A-W01"]["status"] = "인계 대기"                # 제출보관함: 칸 예약 유지(교차 검증이 틀리면 되돌림)
        self.assertEqual(self.s.layout()["summary"]["used"], 2)
        self.items.db["A-W01"]["status"] = "인계 완료"                # 건넴 → 칸 비움
        self.items.db["A-W02"]["status"] = "인계 완료"
        self.assertEqual(self.s.assign("A-W05", "R4-1", override_category=True)["slot_id"], "R4-1")   # 화면 새로고침 없이 바로 넣기
        self.s.release(slot_id="R4-1")
        self.assertEqual(self.s.layout()["summary"]["used"], 0)
        self.assertEqual(self.s.assign("A-W03", "R4-1", override_category=True)["slot_id"], "R4-1")

    def test_pose_validation(self):
        self.assertEqual(self.s.set_pose("R2-1", "pose_3")["pose_name"], "pose_3")
        self.assertIsNone(self.s.set_pose("R2-1", "")["pose_name"])
        for bad in ("Pose1", "1pose", "pose-1", "a" * 33, 3):
            with self.assertRaises(StorageError):
                self.s.set_pose("R2-1", bad)
        with self.assertRaises(StorageError):
            self.s.set_pose("R7-1", "pose_1")

    def test_record_check(self):
        row = self.s.record_check({"section": "R1", "expected_count": 2, "detected_count": 2, "status": "count_match"})
        self.assertEqual((row["id"], row["status"], row["item_id"]), (1, "count_match", None))
        self.s.record_check({"section": "R1", "expected_count": 2, "detected_count": None,
                             "status": "invalid_calibration", "item_id": "A-W03"})
        self.assertEqual([r["id"] for r in self.s.recent_checks()], [2, 1])
        for bad in ({"section": "R1", "expected_count": 2, "status": "ok"},
                    {"section": "R1", "expected_count": -1, "status": "count_match"},
                    {"section": "R1", "expected_count": 1, "status": "count_match", "image": "x.jpg"},
                    {"section": "R1", "expected_count": True, "status": "count_match"}, []):
            with self.assertRaises(StorageError):
                self.s.record_check(bad)
        with self.assertRaises(StorageError):
            self.s.record_check({"section": "R9", "expected_count": 1, "status": "count_match"})

    def test_without_lookup_allows_any_category(self):
        s = MemoryStorageStore()
        self.assertEqual(s.assign("A-W01", "R1-1")["slot_id"], "R1-1")
        with self.assertRaises(StorageError):
            s.assign("A-W02", "H-1")


class MigrationMatchesLayoutTest(unittest.TestCase):
    def test_seed_rows_match_layout(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        sections = re.findall(r"\('(\w+)',\s*'([^']+)',\s*'(shelf|handover)',\s*'\{([^}]*)\}',\s*(\d+)\)", sql)
        got = {c: (lb, k, [x for x in cats.split(",") if x]) for c, lb, k, cats, _ in sections}
        # 009 가 바꾼 행(이름·품목)을 007 시작값에 적용하면 LAYOUT 과 같아야 한다
        fix9 = (ROOT / "center" / "migrations" / "009_storage_categories_photo_1106.sql").read_text(encoding="utf-8")
        for lb, cats, code, old in re.findall(r"SET label = '([^']+)', allowed_categories = '\{([^}]*)\}'\s*"
                                              r"WHERE section_code = '(\w+)' AND allowed_categories = '\{([^}]*)\}'", fix9):
            self.assertEqual(",".join(got[code][2]), old)
            got[code] = (lb, got[code][1], cats.split(","))
        self.assertEqual([(c, *got[c]) for c, _, _, _, _ in sections],
                         [(c, lb, k, al) for c, lb, k, al, _, _ in LAYOUT])
        slots = re.findall(r"\('([A-Z]\d?-\d)',\s*'(\w+)',\s*(\d+),\s*(NULL|'[^']*')\)", sql)
        # 008 이 바꾼 메모(옛 값 → 새 값)를 007 시작값에 적용하면 LAYOUT 과 같아야 한다
        fix = (ROOT / "center" / "migrations" / "008_storage_layout_photo_1106.sql").read_text(encoding="utf-8")
        renames = {old: new for new, old in re.findall(r"SET note = '([^']+)' WHERE .*?note = '([^']+)'", fix)}
        got = [(sid, c, no, f"'{renames.get(n[1:-1], n[1:-1])}'" if n != "NULL" else n) for sid, c, no, n in slots]
        expect = [(f"{c}-{i}", c, str(i), "NULL" if note is None else f"'{note}'")
                  for c, _, _, _, n, note in LAYOUT for i in range(1, n + 1)]
        self.assertEqual(got, expect)

    def test_on_shelf_and_check_statuses_match_sql(self):
        from agents.storage import CHECK_STATUSES, RELEASE_STATUSES
        sql = MIGRATION.read_text(encoding="utf-8")
        block = sql[sql.index("status IN ('count_match'"):]
        self.assertEqual(re.findall(r"'(\w+)'", block[:block.index(")),")]), list(CHECK_STATUSES))
        latest = (ROOT / "center" / "migrations" / "011_storage_release_on_done_1106.sql").read_text(encoding="utf-8")
        self.assertIn("NEW.status IN ('" + "', '".join(RELEASE_STATUSES) + "')", latest)   # 11/6 인계 완료 때만
        from agents.contracts import ITEM_STATUS
        self.assertTrue(set(ON_SHELF) | set(RELEASE_STATUSES) <= set(ITEM_STATUS))

    def test_is_idempotent_style(self):
        sql = MIGRATION.read_text(encoding="utf-8")
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 4)
        self.assertEqual(sql.count("ON CONFLICT"), 2)          # 시작 배치 두 묶음(있으면 그대로)
        self.assertIn("DROP TRIGGER IF EXISTS", sql)


class StorageExportToolTest(unittest.TestCase):
    def test_demo_and_store_exit_codes(self):
        from tools import storage_export
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(storage_export.main(["--demo"]), 0)
        self.assertEqual(set(json.loads(out.getvalue())), {"sections", "inventory", "warnings", "exported_at"})
        s = MemoryStorageStore()
        s.assign("A-W01", "R4-1")
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(storage_export.main([], store=s), 2)       # 자세 없는 칸에 물건 → 경고
        self.assertIn("R4-1", err.getvalue())

    def test_no_dsn(self):
        from tools import storage_export
        old = os.environ.pop("DATABASE_URL", None)
        try:
            import tools.envfile as ef
            orig, ef.load_env = ef.load_env, (lambda *a, **k: None)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(storage_export.main([]), 1)
        finally:
            ef.load_env = orig
            if old is not None:
                os.environ["DATABASE_URL"] = old

    def test_postgres_store_hides_dsn(self):
        self.assertEqual(repr(PostgresStorageStore("postgresql://u:secret@h/db")), "PostgresStorageStore(dsn=***)")
        with self.assertRaises(ValueError):
            PostgresStorageStore("")


@unittest.skipUnless(os.environ.get("LF_SUPPORT_TEST_DSN"), "disposable PostgreSQL not configured")
class PostgresStorageTest(unittest.TestCase):
    """버리는 DB lf_support_test 에서만(tests/test_center_postgres.py 와 같은 규칙)"""

    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.dsn = os.environ["LF_SUPPORT_TEST_DSN"]
        with psycopg.connect(cls.dsn) as conn:
            if conn.info.dbname != "lf_support_test":
                raise RuntimeError("Integration tests require disposable database lf_support_test")
            conn.execute((ROOT / "center/schema.sql").read_text(encoding="utf-8"))
            for path in sorted((ROOT / "center/migrations").glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))

    def setUp(self):
        import psycopg
        with psycopg.connect(self.dsn) as conn:
            conn.execute("TRUNCATE storage_assignment, inventory_check")
            conn.execute("UPDATE storage_slot SET pose_name = NULL")
            conn.execute("INSERT INTO machine(machine_id,kind,line,station) VALUES('KIOSK-A','kiosk','2호선','해운대') "
                         "ON CONFLICT DO NOTHING")
            for iid, st, cat in (("A-W01", "본센터 보관", "지갑"), ("A-W02", "본센터 보관", "지갑"),
                                 ("A-W04", "등록기계 보관", "USB")):
                conn.execute("INSERT INTO item(item_id,machine_id,place_text,category,status) VALUES(%s,'KIOSK-A','시험',%s,%s) "
                             "ON CONFLICT (item_id) DO UPDATE SET status=EXCLUDED.status, category=EXCLUDED.category",
                             (iid, cat, st))
        self.s = PostgresStorageStore(self.dsn)

    def test_round_trip_and_trigger(self):
        import psycopg
        self.s.assign("A-W01", "R4-1")
        with self.assertRaises(StorageConflict):
            self.s.assign("A-W02", "R4-1")
        with self.assertRaises(StorageConflict):
            self.s.assign("A-W04", "R2-1")
        with self.assertRaises(StorageError):
            self.s.assign("A-W02", "R1-1")
        self.s.assign("A-W01", "R4-2")
        self.s.set_pose("R4-2", "pose_2")
        out = self.s.export()
        self.assertEqual(out["inventory"], {"A-W01": {"section": "R4", "slot": "2"}})
        gunte_load_storage(out)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE item SET status='인계 대기' WHERE item_id='A-W01'")
        self.assertEqual(self.s.layout()["summary"]["used"], 1)       # 11/6 인계 대기는 칸 예약 유지
        with psycopg.connect(self.dsn) as conn:
            conn.execute("UPDATE item SET status='인계 완료' WHERE item_id='A-W01'")
        self.assertEqual(self.s.layout()["summary"]["used"], 0)
        row = self.s.record_check({"section": "R4", "expected_count": 0, "detected_count": 0, "status": "count_match"})
        self.assertEqual(self.s.recent_checks(5)[0]["id"], row["id"])
