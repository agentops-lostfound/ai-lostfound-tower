"""Reproduced LF-9 stale reset, malformed input, concurrency and error boundaries."""
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from agents.center_api import create_app
from center.demo_collections import DemoCollections


class CollectionRedteam(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DemoCollections(Path(tmp.name) / 'demo.sqlite3')
        self.client = TestClient(create_app(collections=self.store, demo=True), base_url='http://127.0.0.1:8110', raise_server_exceptions=False)
        self.payload = {'machine_id': 'KIOSK-A', 'item_ids': ['A-W01', 'A-W02'], 'request_id': 'redteam-request-001'}

    def test_old_reset_revision_cannot_pickup_freshly_seeded_items(self):
        revision = self.client.get('/collection-dashboard').json().get('revision', 'missing')
        headers = {'x-demo-revision': revision}
        self.assertEqual(self.client.post('/collections', json=self.payload, headers=headers).status_code, 200)
        self.assertEqual(self.client.post('/demo/reset', json={'confirm': 'RESET_DEMO'}, headers=headers).status_code, 200)
        result = self.client.post('/collections', json=self.payload, headers=headers)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()['detail']['code'], 'stale_demo')
        self.assertEqual(len(self.store.dashboard()['collections']), 0)

    def test_reset_revision_is_transactional_and_survives_reopening(self):
        original = self.store.dashboard().get('revision')
        self.assertIsInstance(original, str)
        self.store.reset(revision=original)
        current = DemoCollections(self.store.path).dashboard()['revision']
        self.assertNotEqual(original, current)
        with self.assertRaises(ValueError):
            self.store.pickup('KIOSK-A', ['A-W01'], 'stale-request-001', revision=original)
        self.assertEqual(self.store.dashboard()['event_count'], 0)

    def test_missing_revision_or_old_reset_cannot_mutate(self):
        self.assertEqual(self.client.post('/collections', json=self.payload).status_code, 409)
        revision = self.store.dashboard()['revision']
        headers = {'x-demo-revision': revision}
        self.client.post('/demo/reset', json={'confirm': 'RESET_DEMO'}, headers=headers)
        self.assertEqual(self.client.post('/demo/reset', json={'confirm': 'RESET_DEMO'}, headers=headers).status_code, 409)

    def test_invalid_and_extreme_collection_numbers_never_cause_server_errors(self):
        for cid in ['-1', '0', str(2**100), 'not-an-integer']:
            with self.subTest(cid=cid):
                self.assertEqual(self.client.get('/collections/' + cid).status_code, 422)

    def test_malformed_staff_header_is_rejected_without_internal_error(self):
        client = TestClient(create_app(staff_key='trusted-key'), raise_server_exceptions=False)
        for headers in [[(b'x-staff-key', b'\xff')], [('x-staff-key', 'x' * 5000)], [('x-staff-key', 'trusted-key'), ('x-staff-key', 'wrong')]]:
            with self.subTest(headers=repr(headers)[:50]):
                result = client.get('/collections/1', headers=headers)
                self.assertEqual(result.status_code, 403)
                self.assertNotIn('trusted-key', result.text)

    def test_competing_pickups_and_split_arrivals_do_not_duplicate_records(self):
        def pickup(index):
            try:
                return self.store.pickup('KIOSK-A', ['A-W01', 'A-W02'], 'competing-request-' + str(index))
            except ValueError:
                return None
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(pickup, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)
        cid = next(r['collection_id'] for r in results if r)
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda iid: self.store.arrive(cid, [iid]), ['A-W01', 'A-W02']))
        board = self.store.dashboard()
        self.assertEqual(board['event_count'], 4)
        self.assertEqual(board['alerts'], [])
        self.assertTrue(self.store.get(cid)['arrived_at'])

    def test_reset_and_old_pickup_are_serialized_inside_transaction(self):
        for index in range(10):
            revision = self.store.dashboard()['revision']
            def pickup():
                try:
                    self.store.pickup('KIOSK-A', ['A-W01'], 'racing-request-' + str(index), revision=revision)
                except ValueError:
                    pass
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(pickup)
                second = pool.submit(self.store.reset, revision=revision)
                first.result()
                second.result()
            self.assertEqual(self.store.dashboard()['collections'], [])
            self.assertEqual(self.store.dashboard()['event_count'], 0)

    def test_store_error_response_does_not_reveal_sql_or_local_paths(self):
        with self.store.connection(write=True) as db:
            db.execute('ALTER TABLE demo_item RENAME TO hidden_demo_item')
        result = self.client.get('/collection-dashboard')
        self.assertEqual(result.status_code, 503)
        for private in ['demo_item', 'sqlite3', str(self.store.path), 'SELECT', 'Traceback']:
            self.assertNotIn(private, result.text)

    def test_duplicate_json_deep_json_sql_injection_and_static_escape(self):
        self.client.headers['x-demo-revision'] = self.store.dashboard()['revision']
        self.assertEqual(self.client.post('/collections', content='{"machine_id":"KIOSK-A","machine_id":"KIOSK-C"}', headers={'content-type': 'application/json'}).status_code, 422)
        self.assertEqual(self.client.post('/collections', content='{"nested":' + '[' * 40 + '0' + ']' * 40 + '}', headers={'content-type': 'application/json'}).status_code, 422)
        for body in [dict(self.payload, machine_id="KIOSK-A'; DROP TABLE demo_item;--"), dict(self.payload, item_ids=['A-W01 OR 1=1']), dict(self.payload, item_ids={'A-W01': True})]:
            self.assertEqual(self.client.post('/collections', json=body).status_code, 409)
        self.assertEqual(self.client.get('/collection-assets/%2e%2e/%2e%2e/AGENTS.md').status_code, 404)
        self.assertEqual(self.store.dashboard()['event_count'], 0)

    def test_invalid_revision_never_creates_server_error_or_changes_state(self):
        for revision in [b'f' * 1000, b'not-a-revision', b'\xff']:
            result = self.client.post('/collections', json=self.payload, headers=[(b'x-demo-revision', revision)])
            self.assertEqual(result.status_code, 409)
        self.assertEqual(self.store.dashboard()['collections'], [])
