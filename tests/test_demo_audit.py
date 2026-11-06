import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from agents.center_api import create_app
from center.demo_collections import DemoCollections
from center.demo_audit import audit_demo
from center.statistics import plan_count


class DemoAuditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DemoCollections(Path(tmp.name) / 'demo.sqlite3')

    def pickup(self):
        return self.store.pickup('KIOSK-A', ['A-W01', 'A-W02'], 'audit-request-001')['collection_id']

    def test_clean_seed_pickup_zero_partial_and_full_arrival_are_consistent(self):
        self.assertEqual(audit_demo(self.store)['issue_count'], 0)
        cid = self.pickup()
        for ids in [None, [], ['A-W01'], ['A-W02']]:
            if ids is not None:
                self.store.arrive(cid, ids)
            with self.subTest(ids=ids):
                self.assertEqual(audit_demo(self.store)['status'], 'ok')

    def test_missing_duplicate_history_and_status_mismatch_are_reported_without_repair(self):
        cid = self.pickup()
        with self.store.connection(write=True) as db:
            db.execute("DELETE FROM demo_event WHERE item_id='A-W01'")
            db.execute("INSERT INTO demo_event(collection_id,item_id,status,at) VALUES(?,'A-W02','회수 중','2026-11-05')", (cid,))
            db.execute("UPDATE demo_item SET status='본센터 보관' WHERE item_id='A-W01'")
        before = self.store.dashboard()
        result = audit_demo(self.store)
        self.assertIn('history_mismatch', [i['code'] for i in result['issues']])
        self.assertIn('status_mismatch', [i['code'] for i in result['issues']])
        self.assertEqual(before, self.store.dashboard())

    def test_zero_arrival_review_detects_missing_alert_even_when_all_alerts_deleted(self):
        cid = self.pickup()
        self.store.arrive(cid, [])
        with self.store.connection(write=True) as db:
            db.execute('DELETE FROM demo_alert')
        result = audit_demo(self.store)
        self.assertEqual(sum(i['code'] == 'missing_alert' for i in result['issues']), 2)

    def test_orphan_alert_member_wrong_machine_and_false_completion_are_detected(self):
        cid = self.pickup()
        with self.store.connection(write=True) as db:
            db.execute("UPDATE demo_collection SET arrived_at='2026-11-05',machine_id='KIOSK-C'")
            db.execute("INSERT INTO demo_member VALUES(999,'A-W03',0)")
            db.execute("INSERT INTO demo_alert(collection_id,item_id,created_at) VALUES(?,'S-W01','2026-11-05')", (cid,))
        codes = {i['code'] for i in audit_demo(self.store)['issues']}
        self.assertTrue({'orphan_member','machine_mismatch','completion_mismatch','invalid_alert'} <= codes)

    def test_audit_is_consistent_during_arrival_and_does_not_expose_unsafe_ids(self):
        cid = self.pickup()
        with ThreadPoolExecutor(2) as pool:
            read = pool.submit(lambda: [audit_demo(self.store)['issue_count'] for _ in range(8)])
            write = pool.submit(self.store.arrive, cid, ['A-W01','A-W02'])
            write.result()
            self.assertEqual(read.result(), [0] * 8)
        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO demo_alert(collection_id,item_id,created_at) VALUES(999,'unsafe-id-value','2026-11-05')")
        self.assertNotIn('unsafe-id-value', str(audit_demo(self.store)))

    def test_audit_api_is_demo_only_and_reopening_preserves_review_marker(self):
        cid = self.pickup()
        self.store.arrive(cid, [])
        reopened = DemoCollections(self.store.path)
        client = TestClient(create_app(collections=reopened, demo=True), base_url='http://127.0.0.1:8110')
        result = client.get('/collection-audit')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'ok')
        self.assertIn('실물', result.json()['scope'])
        self.assertEqual(TestClient(create_app(staff_key='test')).get('/collection-audit').status_code, 404)

    def test_statistics_accepts_spaced_and_spoken_category_names_without_dropping_conditions(self):
        for alias, category in [('보조 배터리','보조배터리'), ('핸드 크림','핸드크림'), ('유에스비','USB'), ('핸드폰','모형폰')]:
            self.assertEqual(plan_count('오늘 '+alias+' 접수 몇 개?').category, category)
        with self.assertRaises(ValueError):
            plan_count('오늘 파란 보조 배터리 접수 몇 개?')
