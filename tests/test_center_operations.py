import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from center.collections import CollectionStore, CollectionError, item_ids
from center.statistics import plan_count, Statistics


class StatisticsTests(unittest.TestCase):
    def test_korean_machine_suffix_and_kst_boundary(self):
        q = plan_count("오늘 등록기계 A에 들어온 USB 몇 개?", datetime(2026, 11, 3, 16, tzinfo=timezone.utc))
        self.assertEqual(q.day.isoformat(), "2026-11-04")
        self.assertEqual(q.machine_id, "KIOSK-A")
        self.assertEqual(q.category, "USB")
        self.assertEqual(q.params[0].isoformat(), "2026-11-04T00:00:00+09:00")
        self.assertEqual(q.sql.count("%s"), len(q.params))
        self.assertNotIn("USB", q.sql)

    def test_reject_unsupported_filters_private_data_and_sql(self):
        for text in ["오늘 이름별 접수 몇 건", "오늘 USB 접수 몇 개; DROP TABLE item", "이번 주 USB 접수 몇 개",
                     "오늘 등록기계 123 USB 접수 몇 개", "오늘 검정 USB 접수 몇 개", "오늘 어제 USB 접수 몇 개",
                     "오늘 지갑 USB 접수 몇 개", "오늘 회수된 USB 몇 개"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                plan_count(text)

    def test_query_runs_read_only_under_stats_role(self):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (3,)
        result = Statistics(lambda: conn).ask("2026-11-04 전체 물건 접수 몇 건?")
        self.assertEqual(result["count"], 3)
        calls = cur.execute.call_args_list
        self.assertEqual(calls[0].args[0], "SET TRANSACTION READ ONLY")
        self.assertEqual(calls[1].args[0], "SET LOCAL ROLE lf_stats_reader")
        self.assertIn("public.stats_item", calls[-1].args[0])


class CollectionTests(unittest.TestCase):
    def test_ids_must_be_unique_and_valid(self):
        for value in [[], ["A-W01", "A-W01"], ["not-an-id"], "A-W01"]:
            with self.subTest(value=value), self.assertRaises(CollectionError):
                item_ids(value)

    def connection(self, fetches):
        conn = MagicMock(); conn.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect = fetches
        return conn, cur

    def test_pickup_validation_before_any_mutation(self):
        conn, cur = self.connection([None])
        cur.fetchall.return_value = [("A-W01", "KIOSK-A", "本센터 보관")]
        with self.assertRaises(CollectionError):
            CollectionStore(lambda: conn).pickup("KIOSK-A", ["A-W01"], "request001")
        self.assertFalse(any(c.args[0].startswith(("UPDATE", "INSERT")) for c in cur.execute.call_args_list))
        self.assertIsNotNone(conn.__exit__.call_args.args[0])

    def test_arrival_rejects_foreign_item_before_mutation(self):
        conn, cur = self.connection([(1,)])
        cur.fetchall.return_value = [("A-W01", False)]
        with self.assertRaises(CollectionError):
            CollectionStore(lambda: conn).arrive(1, ["A-W02"])
        self.assertFalse(any(c.args[0].startswith(("UPDATE", "INSERT")) for c in cur.execute.call_args_list))

    def test_arrival_retry_does_not_duplicate_status_log(self):
        now = datetime.now(timezone.utc)
        conn, cur = self.connection([(1,), ("KIOSK-A", now, now)])
        cur.fetchall.side_effect = [[("A-W01", True)], [("A-W01", True)]]
        result = CollectionStore(lambda: conn).arrive(1, ["A-W01"])
        self.assertEqual(result["missing_item_ids"], [])
        self.assertFalse(any("INSERT INTO item_status_log" in c.args[0] for c in cur.execute.call_args_list))

    def test_partial_arrival_queues_missing_and_not_completes(self):
        now = datetime.now(timezone.utc)
        conn, cur = self.connection([(1,), ("KIOSK-A", now, None)])
        cur.fetchall.side_effect = [[("A-W01", False), ("A-W02", False)], [("A-W01", "회수 중")],
                                  [("A-W01", True), ("A-W02", False)]]
        result = CollectionStore(lambda: conn).arrive(1, ["A-W01"])
        self.assertEqual(result["missing_item_ids"], ["A-W02"])
        self.assertFalse(any("UPDATE collection SET arrived_at" in c.args[0] for c in cur.execute.call_args_list))
        self.assertTrue(any("INSERT INTO collection_alert" in c.args[0] for c in cur.execute.call_args_list))


if __name__ == "__main__":
    unittest.main()
