"""Opt-in integration tests: ONLY a disposable database named lf_support_test."""
import os
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from center.collections import CollectionStore, CollectionError
from center.statistics import Statistics
from center.places import Places
from discord_ops.reporter import Reporter


@unittest.skipUnless(os.environ.get("LF_SUPPORT_TEST_DSN"), "disposable PostgreSQL not configured")
class PostgresIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        cls.connect = staticmethod(lambda: psycopg.connect(os.environ["LF_SUPPORT_TEST_DSN"]))
        with cls.connect() as conn:
            if conn.info.dbname != "lf_support_test":
                raise RuntimeError("Integration tests require disposable database lf_support_test")
            root = Path(__file__).resolve().parents[1]
            conn.execute((root / "center/schema.sql").read_text(encoding="utf-8"))
            for path in sorted((root / "center/migrations").glob("*.sql")):
                conn.execute(path.read_text(encoding="utf-8"))

    def setUp(self):
        with self.connect() as conn:
            conn.execute("TRUNCATE machine CASCADE")
            conn.execute("TRUNCATE place CASCADE")
            conn.execute("INSERT INTO machine(machine_id,kind,line,station) VALUES('KIOSK-A','kiosk','2호선','해운대'),('KIOSK-B','kiosk','1호선','중앙')")
            for iid in ("A-W01", "A-W02"):
                conn.execute("INSERT INTO item(item_id,machine_id,place_text,category,received_at) VALUES(%s,'KIOSK-A','시험 장소','USB','2026-11-04 00:30+09')", (iid,))
        self.store = CollectionStore(self.connect)

    def test_concurrent_retry_and_partial_then_complete_arrival(self):
        def pickup(_):
            return self.store.pickup("KIOSK-A", ["A-W01", "A-W02"], "same-request-001")
        with ThreadPoolExecutor(2) as executor:
            first, retry = list(executor.map(pickup, range(2)))
        self.assertEqual(first["collection_id"], retry["collection_id"])
        cid = first["collection_id"]
        partial = self.store.arrive(cid, ["A-W01"])
        self.assertEqual(partial["missing_item_ids"], ["A-W02"])
        self.assertIsNone(partial["arrived_at"])
        self.store.arrive(cid, ["A-W01"])
        reporter = Reporter(dry_run=True)
        self.assertEqual(self.store.dispatch(reporter), 0)
        self.assertEqual(len(reporter.messages), 1)
        complete = self.store.arrive(cid, ["A-W02"])
        self.assertIsNotNone(complete["arrived_at"])
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM collection").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM item_status_log").fetchone()[0], 4)
            self.assertEqual(conn.execute("SELECT count(*) FROM item WHERE status='본센터 보관'").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM collection_alert WHERE resolved_at IS NULL").fetchone()[0], 0)

    def test_invalid_pickup_rolls_back_entire_batch(self):
        with self.assertRaises(CollectionError):
            self.store.pickup("KIOSK-A", ["A-W01", "A-W99"], "rollback-request")
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM collection").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT status FROM item WHERE item_id='A-W01'").fetchone()[0], "등록기계 보관")

    def test_zero_arrivals_and_explicit_deadline(self):
        cid = self.store.pickup("KIOSK-A", ["A-W01", "A-W02"], "missing-request")["collection_id"]
        self.assertEqual(len(self.store.arrive(cid, [])["missing_item_ids"]), 2)
        self.assertEqual(self.store.overdue(datetime(2100, 1, 1, tzinfo=timezone.utc)), 0)

    def test_statistics_counts_and_role_denies_private_tables_and_writes(self):
        result = Statistics(self.connect).ask("오늘 등록기계 A에 들어온 USB 몇 개?", datetime(2026, 11, 4, 3, tzinfo=timezone.utc))
        self.assertEqual(result["count"], 2)
        import psycopg
        for query in ("SELECT * FROM claim", "SELECT * FROM finder_contact", "UPDATE item SET category='지갑'"):
            with self.connect() as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute("SET LOCAL ROLE lf_stats_reader")
                with self.assertRaises(psycopg.Error):
                    conn.execute(query)

    def test_place_upsert_and_paging(self):
        store = Places(self.connect)
        for n in range(7):
            store.put("2호선", "해운대", f"장소{n}")
        one = store.put("2호선", "해운대", "장소0")
        self.assertEqual(one, store.put("2호선", "해운대", "장소0"))
        page = store.recommend("KIOSK-A")
        self.assertEqual(len(page["places"]), 5)
        self.assertEqual(len(store.recommend("KIOSK-A", page["next_offset"])["places"]), 2)
