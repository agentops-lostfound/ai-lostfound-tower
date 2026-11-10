"""11/10 접수 지우기 도구(tools/purge_items.py) 시험

확인하는 것
- 번호 범위 펴기와 형식 검사
- 미리보기는 아무것도 지우지 않는다. --apply 때만 물건·상태 기록·연락처를 지운다
- 찾기 요청·반환·보관 칸 등에 걸린 물건은 지우지 않고 이유를 알려 준다
- 진짜 PostgreSQL 시험은 LF_TEST_DATABASE_URL 이 있을 때만(시험이 만든 번호만 지움)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import purge_items  # noqa: E402


class ExpandTest(unittest.TestCase):
    def test_range_and_single(self):
        self.assertEqual(purge_items.expand(["A-20261110-0001..0003", "H-20261110-0006", "A-20261110-0002"]),
                         ["A-20261110-0001", "A-20261110-0002", "A-20261110-0003", "H-20261110-0006"])

    def test_bad_input(self):
        for bad in ("A-1", "A-20261110-0005..0001", "A-20261110-0001..9999", "'; DROP TABLE item; --", "a-20261110-0001"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    purge_items.expand([bad])


class FakeCursor:
    def __init__(self, db):
        self.db, self.rows, self.log = db, [], db["log"]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=()):
        self.log.append(sql)
        ids = list(params[0])
        if sql.startswith("SELECT item_id FROM item"):
            self.rows = [(i,) for i in ids if i in self.db["item"]]
        elif sql.startswith("SELECT DISTINCT item_id FROM"):
            table = sql.split()[4]
            self.rows = [(i,) for i in ids if i in self.db.get(table, set())]
        elif sql.startswith("DELETE FROM"):
            table = sql.split()[2]
            self.db.setdefault(table, set()).difference_update(ids)
            self.rows = []

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return FakeCursor(self.db)


class PurgeTest(unittest.TestCase):
    def setUp(self):
        self.db = {"item": {"A-20261110-0001", "A-20261110-0002", "A-20261110-0003"}, "item_status_log": {"A-20261110-0001", "A-20261110-0002"},
                   "finder_contact": {"A-20261110-0001"}, "storage_assignment": {"A-20261110-0003"}, "return_case": {"A-20261110-0003"}, "log": []}
        self.ids = ["A-20261110-0001", "A-20261110-0002", "A-20261110-0003", "A-20261110-0009"]

    def run_tool(self, apply):
        return purge_items.purge_items("dsn", self.ids, apply=apply, connect=lambda d: FakeConn(self.db))

    def test_preview_deletes_nothing(self):
        r = self.run_tool(False)
        self.assertEqual(r["deleted"], ["A-20261110-0001", "A-20261110-0002"])
        self.assertEqual(r["missing"], ["A-20261110-0009"])
        self.assertEqual(r["blocked"], {"A-20261110-0003": ["반환 기록", "보관 칸"]})
        self.assertEqual(len(self.db["item"]), 3)
        self.assertFalse([s for s in self.db["log"] if s.startswith("DELETE")])

    def test_apply_deletes_owned_rows_then_item(self):
        r = self.run_tool(True)
        self.assertEqual(r["deleted"], ["A-20261110-0001", "A-20261110-0002"])
        self.assertEqual(self.db["item"], {"A-20261110-0003"})                 # 다른 기록에 걸린 물건은 남는다
        self.assertEqual(self.db["finder_contact"], set())
        self.assertEqual(self.db["item_status_log"], set())
        deletes = [s.split()[2] for s in self.db["log"] if s.startswith("DELETE")]
        self.assertEqual(deletes, ["finder_contact", "item_status_log", "item"])   # 딸린 기록 먼저, 물건은 마지막

    def test_cli_without_database_url(self):
        old = os.environ.pop("DATABASE_URL", None)
        try:
            import tools.envfile as envfile
            real = envfile.load_env
            envfile.load_env = lambda *a, **k: None
            try:
                self.assertEqual(purge_items.main(["A-20261110-0001"]), 2)
                self.assertEqual(purge_items.main(["틀린번호"]), 2)
            finally:
                envfile.load_env = real
        finally:
            if old is not None:
                os.environ["DATABASE_URL"] = old


@unittest.skipUnless(os.environ.get("LF_TEST_DATABASE_URL"), "진짜 PostgreSQL 시험은 LF_TEST_DATABASE_URL 이 있을 때만")
class RealDbTest(unittest.TestCase):
    IDS = ["Z-20990101-0001", "Z-20990101-0002"]

    def setUp(self):
        import psycopg
        self.dsn = os.environ["LF_TEST_DATABASE_URL"]
        with psycopg.connect(self.dsn) as c, c.cursor() as cur:
            cur.execute("SELECT machine_id FROM machine ORDER BY machine_id LIMIT 1")
            machine = cur.fetchone()[0]
            for iid in self.IDS:
                cur.execute("DELETE FROM storage_assignment WHERE item_id = %s", (iid,))
                cur.execute("DELETE FROM finder_contact WHERE item_id = %s", (iid,))
                cur.execute("DELETE FROM item_status_log WHERE item_id = %s", (iid,))
                cur.execute("DELETE FROM item WHERE item_id = %s", (iid,))
                cur.execute("INSERT INTO item (item_id, machine_id, place_text, status, category) VALUES (%s, %s, '시험', '등록기계 보관', '확인 불가')",
                            (iid, machine))
                cur.execute("INSERT INTO item_status_log (item_id, to_status, changed_by) VALUES (%s, '등록기계 보관', 'kiosk')", (iid,))
            cur.execute("SELECT slot_id FROM storage_slot s WHERE NOT EXISTS (SELECT 1 FROM storage_assignment a WHERE a.slot_id = s.slot_id) ORDER BY slot_id LIMIT 1")
            self.slot = cur.fetchone()[0]
            cur.execute("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES (%s, %s, 'system')", (self.slot, self.IDS[1]))

    def tearDown(self):
        import psycopg
        with psycopg.connect(self.dsn) as c, c.cursor() as cur:
            for iid in self.IDS:
                cur.execute("DELETE FROM storage_assignment WHERE item_id = %s", (iid,))
                cur.execute("DELETE FROM item_status_log WHERE item_id = %s", (iid,))
                cur.execute("DELETE FROM item WHERE item_id = %s", (iid,))

    def test_real_delete(self):
        import psycopg
        r = purge_items.purge_items(self.dsn, self.IDS, apply=False)
        self.assertEqual((r["deleted"], list(r["blocked"])), ([self.IDS[0]], [self.IDS[1]]))
        r = purge_items.purge_items(self.dsn, self.IDS, apply=True)
        self.assertEqual(r["deleted"], [self.IDS[0]])
        with psycopg.connect(self.dsn) as c, c.cursor() as cur:
            cur.execute("SELECT item_id FROM item WHERE item_id = ANY(%s) ORDER BY 1", (self.IDS,))
            self.assertEqual([x[0] for x in cur.fetchall()], [self.IDS[1]])      # 보관 칸에 든 물건은 남는다
            cur.execute("SELECT count(*) FROM item_status_log WHERE item_id = %s", (self.IDS[0],))
            self.assertEqual(cur.fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
