"""11/3 DB 확정 사항 시험 — 번호 형식·설명 칸·연락처 보관·바뀐 점 적용(마이그레이션)."""
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents import contracts as c  # noqa: E402
from tools import db_migrate, purge_contacts  # noqa: E402


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


class IdFormatTest(unittest.TestCase):
    def test_make_item_id(self):
        self.assertEqual(c.make_item_id("KIOSK-A", date(2026, 11, 3), 1), "A-20261103-0001")
        self.assertEqual(c.make_item_id("CENTER", date(2026, 12, 31), 9999), "H-20261231-9999")
        for bad in (("KIOSK-Z", 1), ("KIOSK-A", 0), ("KIOSK-A", 10000)):
            with self.assertRaises(ValueError):
                c.make_item_id(bad[0], date(2026, 11, 3), bad[1])

    def test_patterns(self):
        for ok in ("A-20261103-0001", "B-20261231-9999", "A-W03"):
            self.assertTrue(c.ITEM_ID_RE.match(ok), ok)
        for bad in ("A-1103-001", "a-20261103-0001", "A-20261103-1", "AB-20261103-0001", ""):
            self.assertFalse(c.ITEM_ID_RE.match(bad), bad)
        self.assertTrue(c.CLAIM_ID_RE.match("C-20261103-0001"))
        self.assertFalse(c.CLAIM_ID_RE.match("A-20261103-0001"))

    def test_generated_ids_pass_pattern(self):
        for m in c.MACHINE_LETTERS:
            self.assertTrue(c.ITEM_ID_RE.match(c.make_item_id(m, date(2026, 11, 3), 42)))

    def test_demo_seed_ids_pass_pattern(self):
        ids = re.findall(r"VALUES \('([A-Z]-W\d\d)'", read("center/seed_demo.sql"))
        self.assertEqual(len(ids), 7)
        self.assertTrue(all(c.ITEM_ID_RE.match(i) for i in ids))


class SchemaMatchesContractsTest(unittest.TestCase):
    """schema.sql·마이그레이션의 규칙이 contracts.py 와 글자 하나까지 같은지(한쪽만 바꾸는 실수 방지)"""

    def test_patterns_in_sql(self):
        for rel in ("center/schema.sql", "center/migrations/001_db_decisions_1103.sql"):
            sql = read(rel)
            self.assertIn(f"item_id ~ '{c.ITEM_ID_PATTERN}'", sql, rel)
            self.assertIn(f"claim_id ~ '{c.CLAIM_ID_PATTERN}'", sql, rel)

    def test_description_keys_in_sql(self):
        for rel in ("center/schema.sql", "center/migrations/001_db_decisions_1103.sql"):
            m = re.search(r"description - ARRAY\[(.*?)\]", read(rel))
            self.assertEqual(re.findall(r"'([^']+)'", m.group(1)), c.DESCRIPTION_FIELDS, rel)

    def test_validate_description(self):
        self.assertEqual(c.validate_description({"category": "지갑", "color": "검정", "mark": "별"}), [])
        self.assertEqual(len(c.validate_description({"brand": "x", "color": "검정"})), 1)

    def test_vector_is_optional(self):
        self.assertIn("MVP 에서는 실행하지 않음", read("center/schema_vector.sql"))
        self.assertNotIn("schema_vector", read("docker-compose.yml"))   # 자동 실행 목록에 없음

    def test_retention_days_documented(self):
        self.assertIn(f"{c.CONTACT_RETENTION_DAYS}일", read("center/schema.sql"))
        self.assertIn(f"{c.CONTACT_RETENTION_DAYS}일", read("docs/design/database.md"))


class FakeCursorConn:
    """execute 를 기록하고, SQL 종류에 따라 정해 둔 행을 돌려주는 가짜 연결"""

    def __init__(self, rows_by_prefix=None):
        self.executed, self.commits, self.rows_by_prefix = [], 0, rows_by_prefix or {}

    def __call__(self, dsn):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self):
        self.commits += 1

    def cursor(self):
        db = self

        class Cur:
            rows = []

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, sql, params=None):
                db.executed.append((sql, params))
                self.rows = next((v for k, v in db.rows_by_prefix.items() if sql.startswith(k)), [])

            def fetchall(self):
                return self.rows
        return Cur()


class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        for name in ("002_b.sql", "001_a.sql"):
            (self.folder / name).write_text(f"SELECT '{name}';", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_runs_nothing(self):
        db = FakeCursorConn({db_migrate.SQL_DONE: [("001_a.sql",)]})
        self.assertEqual(db_migrate.migrate("x", connect=db, folder=self.folder), ["002_b.sql"])
        self.assertFalse(any("002_b" in s for s, _ in db.executed))

    def test_apply_in_order_and_marks(self):
        db = FakeCursorConn()
        self.assertEqual(db_migrate.migrate("x", apply=True, connect=db, folder=self.folder), ["001_a.sql", "002_b.sql"])
        marks = [p[0] for s, p in db.executed if s == db_migrate.SQL_MARK]
        self.assertEqual(marks, ["001_a.sql", "002_b.sql"])
        ran = [s for s, _ in db.executed if s.startswith("SELECT '")]
        self.assertEqual(ran, ["SELECT '001_a.sql';", "SELECT '002_b.sql';"])

    def test_real_migration_files_exist_in_order(self):
        names = [p.name for p in db_migrate.pending(set())]
        self.assertEqual(names, sorted(names))
        self.assertIn("001_db_decisions_1103.sql", names)

    def test_retry_then_give_up(self):
        calls = []

        def down(dsn):
            calls.append(1)
            raise ConnectionError("꺼짐")
        with self.assertRaises(ConnectionError):
            db_migrate.migrate("x", connect=down, folder=self.folder, wait=0)
        self.assertEqual(len(calls), 1)


class PurgeTest(unittest.TestCase):
    def test_preview_vs_apply_sql(self):
        db = FakeCursorConn({"SELECT": [("A-W01",)], "DELETE": [("A-W01",)]})
        self.assertEqual(purge_contacts.purge_contacts("x", connect=db), ["A-W01"])
        self.assertTrue(db.executed[-1][0].startswith("SELECT"))
        self.assertEqual(db.executed[-1][1], (c.CONTACT_RETENTION_DAYS,))
        purge_contacts.purge_contacts("x", apply=True, connect=db)
        self.assertTrue(db.executed[-1][0].startswith("DELETE"))

    def test_only_handed_over_items(self):
        for sql in (purge_contacts.SQL_PREVIEW, purge_contacts.SQL_DELETE):
            self.assertIn("i.status = '인계 완료'", sql)
            self.assertIn("to_status = '인계 완료'", sql)
            self.assertNotIn("name", sql.split("FROM")[0])   # 이름·전화는 꺼내지 않음


if __name__ == "__main__":
    unittest.main()
