import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agents.center_api import create_app
from center.demo_collections import DemoCollections
from center.collections import CollectionError


class CollectionDeskTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'demo.sqlite3'
        self.store = DemoCollections(self.path)
        self.client = TestClient(create_app(collections=self.store, demo=True), base_url='http://127.0.0.1:8110')

    def pickup(self):
        return self.store.pickup('KIOSK-A', ['A-W01', 'A-W02'], 'demo-request-001')

    def test_demo_is_explicit_and_production_does_not_expose_reset_or_dashboard(self):
        with self.assertRaises(ValueError):
            create_app(collections=MagicMock(), demo=True)
        with self.assertRaises(ValueError):
            create_app(collections=self.store, statistics=MagicMock(), demo=True)
        prod = TestClient(create_app(staff_key='test'))
        self.assertEqual(prod.post('/demo/reset', json={'confirm': 'RESET_DEMO'}).status_code, 404)
        self.assertEqual(prod.get('/collection-dashboard').status_code, 404)
        self.assertEqual(prod.post('/collections', json={}).status_code, 403)

    def test_page_assets_and_health_are_clear_about_synthetic_mode(self):
        page = self.client.get('/collection-desk')
        self.assertEqual(page.status_code, 200)
        self.assertIn('가상 데이터 시연', page.text)
        self.assertIn('디스코드 전송', page.text)
        self.assertEqual(self.client.get('/collection-assets/desk.js').status_code, 200)
        self.assertEqual(self.client.get('/health').json()['team_database_connected'], False)
        self.assertIn("script-src 'self'", page.headers['content-security-policy'])

    def test_pickup_partial_arrival_and_late_arrival_use_existing_api_shapes(self):
        result = self.client.post('/collections', json={'machine_id': 'KIOSK-A', 'item_ids': ['A-W01', 'A-W02'], 'request_id': 'demo-request-001'})
        self.assertEqual(result.status_code, 200)
        cid = result.json()['collection_id']
        result = self.client.post(f'/collections/{cid}/arrivals', json={'item_ids': ['A-W01']}).json()
        self.assertEqual(result['missing_item_ids'], ['A-W02'])
        self.assertIsNone(result['arrived_at'])
        board = self.client.get('/collection-dashboard').json()
        self.assertEqual(len(board['alerts']), 1)
        statuses = {i['item_id']: i['status'] for i in board['items']}
        self.assertEqual(statuses['A-W01'], '본센터 보관')
        self.assertEqual(statuses['A-W02'], '회수 중')
        result = self.client.post(f'/collections/{cid}/arrivals', json={'item_ids': ['A-W02']}).json()
        self.assertTrue(result['arrived_at'])
        self.assertEqual(self.client.get('/collection-dashboard').json()['alerts'], [])

    def test_no_arrival_saves_all_missing_without_completing_batch(self):
        cid = self.pickup()['collection_id']
        result = self.store.arrive(cid, [])
        self.assertEqual(result['missing_item_ids'], ['A-W01', 'A-W02'])
        self.assertIsNone(result['arrived_at'])
        self.assertEqual(len(self.store.dashboard()['alerts']), 2)

    def test_concurrent_same_pickup_is_recorded_once(self):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.pickup(), range(2)))
        self.assertEqual(results[0]['collection_id'], results[1]['collection_id'])
        self.assertEqual(len(self.store.dashboard()['collections']), 1)
        self.assertEqual(self.store.dashboard()['event_count'], 2)

    def test_same_request_cannot_be_reused_for_different_items(self):
        self.pickup()
        with self.assertRaises(CollectionError):
            self.store.pickup('KIOSK-A', ['A-W03'], 'demo-request-001')
        self.assertEqual(self.store.dashboard()['event_count'], 2)

    def test_invalid_pickup_does_not_partially_change_items(self):
        for ids in [['A-W01', 'B-W01'], ['A-W01', 'A-W99'], ['A-W01', 'A-W01']]:
            with self.assertRaises(CollectionError):
                self.store.pickup('KIOSK-A', ids, 'bad-request-001')
        self.assertEqual(self.store.dashboard()['event_count'], 0)
        self.assertTrue(all(i['status'] == '등록기계 보관' for i in self.store.dashboard()['items']))

    def test_invalid_arrival_rolls_back_and_cannot_reverse_completed_items(self):
        cid = self.pickup()['collection_id']
        with self.assertRaises(CollectionError):
            self.store.arrive(cid, ['A-W01', 'B-W01'])
        self.assertEqual(self.store.dashboard()['event_count'], 2)
        self.store.arrive(cid, ['A-W01'])
        self.store.arrive(cid, [])
        self.assertTrue(self.store.get(cid)['items'][0]['arrived'])

    def test_repeated_arrival_has_no_duplicate_history_or_completion_time(self):
        cid = self.pickup()['collection_id']
        first = self.store.arrive(cid, ['A-W01', 'A-W02'])
        retry = self.store.arrive(cid, ['A-W01', 'A-W02'])
        self.assertEqual(first['arrived_at'], retry['arrived_at'])
        self.assertEqual(self.store.dashboard()['event_count'], 4)

    def test_reopening_store_preserves_records(self):
        cid = self.pickup()['collection_id']
        self.store.arrive(cid, ['A-W01'])
        reloaded = DemoCollections(self.path)
        self.assertEqual(reloaded.get(cid)['missing_item_ids'], ['A-W02'])
        self.assertEqual(len(reloaded.dashboard()['items']), 6)

    def test_explicit_reset_only_clears_synthetic_data_and_requires_confirmation(self):
        self.pickup()
        self.assertEqual(self.client.post('/demo/reset', json={}).status_code, 422)
        self.assertEqual(len(self.store.dashboard()['collections']), 1)
        self.assertEqual(self.client.post('/demo/reset', json={'confirm': 'RESET_DEMO'}).status_code, 200)
        board = self.store.dashboard()
        self.assertEqual((len(board['items']), len(board['collections']), len(board['alerts']), board['event_count']), (6, 0, 0, 0))

    def test_cross_origin_rebinding_oversize_and_unknown_collection_are_rejected(self):
        self.assertEqual(self.client.post('/demo/reset', json={'confirm': 'RESET_DEMO'}, headers={'Origin': 'https://example.com'}).status_code, 403)
        self.assertEqual(self.client.get('/collection-dashboard', headers={'Host': 'attacker.example'}).status_code, 400)
        self.assertEqual(self.client.post('/collections', json={'payload': 'x' * 9000}).status_code, 413)
        self.assertEqual(self.client.get('/collections/999').status_code, 404)
        self.assertEqual(self.client.post('/collections/999/arrivals', json={'item_ids': []}).status_code, 409)

    def test_no_automatic_deadline_or_external_delivery(self):
        self.assertEqual(self.client.post('/collections/overdue/check', json={'before': '2100-01-01T00:00:00+09:00'}).status_code, 409)
        self.assertFalse(self.client.get('/health').json()['external_notifications_enabled'])
        self.assertEqual(self.client.post('/alerts/send', json={}).status_code, 404)
