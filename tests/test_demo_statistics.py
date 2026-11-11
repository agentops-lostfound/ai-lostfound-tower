import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from center.demo_collections import DemoCollections
from center.demo_statistics import DemoStatistics, authorize_statistics
from center.statistics import KST, plan_count
from agents.center_api import create_app


class DemoStatisticsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DemoCollections(Path(tmp.name) / 'demo.sqlite3')
        self.stats = DemoStatistics(self.store)
        self.now = datetime(2026, 11, 5, 12, tzinfo=KST)
        self.since = datetime(2026, 11, 5, tzinfo=KST)
        with self.store.connection(write=True) as db:
            db.execute('UPDATE demo_item SET received_at=?', (int(self.since.timestamp() * 1_000_000),))

    def ask(self, question):
        return self.stats.ask(question, now=self.now)

    def test_count_and_sql_are_from_restricted_demo_view(self):
        result = self.ask('오늘 등록기계 A에 들어온 USB 몇 개?')
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['filters']['machine_id'], 'KIOSK-A')
        self.assertEqual(result['filters']['category'], 'USB')
        self.assertEqual(result['source'], 'demo_stats_item')
        self.assertIn('SELECT count(*) FROM demo_stats_item', result['sql'])
        self.assertNotIn('KIOSK-A', result['sql'])
        self.assertEqual(result['parameters'][2:], ['KIOSK-A', 'USB'])

    def test_pickup_and_partial_then_complete_arrival_do_not_change_reception_count(self):
        before = self.ask('오늘 전체 물건 접수 건수 알려줘')['count']
        cid = self.store.pickup('KIOSK-A', ['A-W01', 'A-W02'], 'statistics-request-001')['collection_id']
        self.assertEqual(self.ask('오늘 전체 물건 접수 건수 알려줘')['count'], before)
        for ids in [['A-W01'], ['A-W02']]:
            self.store.arrive(cid, ids)
            self.assertEqual(self.ask('오늘 전체 물건 접수 건수 알려줘')['count'], before)
        self.assertEqual(before, 6)

    def test_korean_midnight_inclusive_start_exclusive_end_and_microseconds(self):
        start = int(self.since.timestamp() * 1_000_000)
        with self.store.connection(write=True) as db:
            db.execute("UPDATE demo_item SET received_at=? WHERE item_id='A-W01'", (start - 1,))
            db.execute("UPDATE demo_item SET received_at=? WHERE item_id='A-W02'", (start + 86_400_000_000,))
            db.execute("UPDATE demo_item SET received_at=? WHERE item_id='A-W03'", (start + 86_400_000_000 - 1,))
        self.assertEqual(self.ask('오늘 전체 물건 접수 건수 알려줘')['count'], 4)
        self.assertEqual(self.ask('어제 전체 물건 접수 건수 알려줘')['count'], 1)
        self.assertEqual(self.ask('2026-11-05 전체 물건 접수 몇 개?')['count'], 4)

    def test_unknown_conditions_never_silently_disappear(self):
        for question in ['오늘 파란 USB 접수 몇 개?', '오늘 중앙역 USB 접수 몇 개?',
                         '오늘 삼성 휴대폰 접수 몇 개?', '오늘 전체 물건 빼고 USB 접수 몇 개?',
                         '오늘 USB 또는 지갑 접수 몇 개?', '9999-12-31 전체 물건 접수 몇 개?']:
            with self.subTest(question=question), self.assertRaises(ValueError):
                self.ask(question)

    def test_private_questions_and_sql_never_reach_database(self):
        for question in ['오늘 전화번호 접수 몇 개?', '오늘 개인정보 USB 접수 몇 개?',
                         '오늘 USB 접수 몇 개; DROP TABLE demo_item', 'SELECT * FROM claim']:
            with self.subTest(question=question), self.assertRaises(ValueError):
                self.ask(question)
        self.assertEqual(len(self.store.dashboard()['items']), 6)

    def test_authorizer_blocks_base_tables_private_columns_metadata_and_writes(self):
        for sql in ['SELECT * FROM demo_item', 'SELECT count(*) FROM demo_item', 'SELECT color FROM demo_item',
                    'SELECT * FROM demo_metadata', 'SELECT * FROM demo_event', 'UPDATE demo_item SET color=NULL',
                    'DROP VIEW demo_stats_item', 'PRAGMA table_info(demo_item)']:
            with self.subTest(sql=sql), self.store.connection() as db:
                db.set_authorizer(authorize_statistics)
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute(sql).fetchall()

    def test_reopen_preserves_reception_timestamps_and_revision(self):
        before = self.ask('오늘 전체 물건 접수 몇 개?')
        reopened = DemoStatistics(DemoCollections(self.store.path)).ask('오늘 전체 물건 접수 몇 개?', now=self.now)
        self.assertEqual(before, reopened)

    def test_demo_api_uses_same_data_and_rejects_sql_payload_and_stale_revision(self):
        client = TestClient(create_app(collections=self.store, demo=True), base_url='http://127.0.0.1:8110')
        client.headers['x-demo-revision'] = self.store.dashboard()['revision']
        result = client.post('/statistics/questions', json={'question': '2026-11-05 전체 물건 접수 몇 개?'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['count'], 6)
        self.assertEqual(client.post('/statistics/questions', json={'question': '오늘 USB 접수 몇 개?', 'sql': 'DROP TABLE demo_item'}).status_code, 422)
        self.store.reset()
        self.assertEqual(client.post('/statistics/questions', json={'question': '오늘 USB 접수 몇 개?'}).status_code, 409)

    def test_fullwidth_input_is_normalized_and_ambiguous_machines_rejected(self):
        self.assertEqual(self.ask('오늘 등록기계 Ａ에 들어온 ＵＳＢ 몇 개?')['count'], 1)
        for question in ['오늘 등록기계 A와 B USB 접수 몇 개?', '오늘 등록기계 Z USB 접수 몇 개? 조건은 파란색', '오늘 어제 전체 접수 몇 건?']:
            with self.assertRaises(ValueError):
                plan_count(question, self.now)
