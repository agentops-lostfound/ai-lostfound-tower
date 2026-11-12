"""LF-9 mounted API boundary and synthetic transaction checks; no network/hardware."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from agents.admin_auth import AdminAuth
from agents.api import build_app
from agents.service import TowerService, demo_backend_factory
from center.demo_collections import DemoCollections
from center.demo_statistics import DemoStatistics
from center.readiness import check_readiness
from discord_ops.reporter import Reporter


class SyntheticCollections:
    def __init__(self, path):
        self.store = DemoCollections(path)

    def pickup(self, *args):
        return self.store.pickup(*args, revision=self.store.dashboard()['revision'])

    def arrive(self, *args):
        return self.store.arrive(*args, revision=self.store.dashboard()['revision'])

    def get(self, cid):
        return self.store.get(cid)

    def dashboard(self):
        return self.store.dashboard()


class CenterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'TOWER_CENTER': '0', 'TOWER_DB': '0', 'TOWER_SIM': '0'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.auth = AdminAuth('synthetic-password', 'synthetic-secret')
        self.stores = {name: MagicMock() for name in ('collections', 'statistics', 'places')}
        self.service = TowerService(demo_backend_factory(), Reporter(dry_run=True))

    def client(self, auth=None, injected=True):
        client = TestClient(build_app(self.service, admin_auth=auth or self.auth,
                                     center_services=self.stores if injected else None),
                            base_url='http://127.0.0.1', raise_server_exceptions=False)
        self.addCleanup(client.close)
        return client

    def login(self, client):
        self.assertEqual(client.post('/api/admin/login', json={'password': 'synthetic-password'}).status_code, 200)

    def test_default_off_does_not_connect_or_expose_center(self):
        with patch('agents.center_integration.environment_services') as factory:
            client = self.client(injected=False)
            self.assertEqual(client.get('/center').status_code, 404)
            self.assertEqual(client.get('/api/admin/center/dashboard').status_code, 404)
            self.assertFalse(client.get('/api/admin/center-enabled').json()['enabled'])
            factory.assert_not_called()

    def test_login_is_required_for_every_mounted_route_and_old_staff_key_cannot_bypass(self):
        client = self.client()
        paths = ['/desk', '/desk.js', '/desk.css', '/dashboard', '/readiness', '/collections/1', '/places?machine_id=KIOSK-A']
        for path in paths:
            self.assertEqual(client.get('/api/admin/center' + path, headers={'x-staff-key': 'test-key'}).status_code, 401, path)
        self.assertEqual(client.post('/api/admin/center/collections', json={}).status_code, 401)
        for store in self.stores.values():
            self.assertEqual(store.mock_calls, [])

    def test_disabled_admin_auth_does_not_open_database_routes(self):
        client = self.client(auth=AdminAuth())
        self.assertEqual(client.get('/api/admin/center/dashboard').status_code, 503)
        self.stores['collections'].dashboard.assert_not_called()

    def test_real_environment_rejects_sim_and_memory_modes(self):
        for db, sim in [('0', '0'), ('1', '1')]:
            with patch.dict(os.environ, {'TOWER_CENTER': '1', 'TOWER_DB': db, 'TOWER_SIM': sim}), patch('agents.center_integration.environment_services', return_value=self.stores):
                client = self.client(injected=False); self.login(client)
                self.assertEqual(client.get('/api/admin/center/dashboard').status_code, 503)
        self.stores['collections'].dashboard.assert_not_called()

    def test_cookie_session_and_logout_cover_child_and_protected_page(self):
        client = self.client(); self.login(client)
        self.assertEqual(client.get('/center').status_code, 200)
        self.assertEqual(client.get('/api/admin/center/desk.css').status_code, 200)
        self.assertIn('crypto.getRandomValues', client.get('/api/admin/center/desk.js').text)
        self.assertIn('회수·통계', client.get('/admin').text)
        client.post('/api/admin/logout')
        self.assertEqual(client.get('/api/admin/center/desk').status_code, 401)

    def test_cross_origin_or_duplicate_origin_never_reaches_write(self):
        client = self.client(); self.login(client)
        for headers in [{'Origin': 'https://example.com'}, {'Sec-Fetch-Site': 'cross-site'},
                        [('Origin', 'http://127.0.0.1'), ('Origin', 'http://127.0.0.1')]]:
            self.assertEqual(client.post('/api/admin/center/collections', json={}, headers=headers).status_code, 403)
        self.stores['collections'].pickup.assert_not_called()

    def test_backend_errors_do_not_expose_connection_details_or_fake_success(self):
        client = self.client(); self.login(client)
        self.stores['collections'].dashboard.side_effect = RuntimeError('synthetic-private-dsn')
        r = client.get('/api/admin/center/dashboard')
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('synthetic-private-dsn', r.text)
        self.assertEqual(r.headers['cache-control'], 'no-store')

    def test_sql_payload_is_not_accepted_by_statistics(self):
        client = self.client(); self.login(client)
        r = client.post('/api/admin/center/statistics/questions', json={'question': '오늘 전체 물건 접수 몇 건?', 'sql': 'SELECT 1'})
        self.assertEqual(r.status_code, 422)
        self.stores['statistics'].ask.assert_not_called()

    def test_synthetic_pickup_partial_late_arrival_and_retry_share_existing_transactions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SyntheticCollections(Path(tmp) / 'synthetic.sqlite3')
            self.stores['collections'] = store
            self.stores['statistics'] = DemoStatistics(store.store)
            client = self.client(); self.login(client)
            payload = {'machine_id': 'KIOSK-A', 'item_ids': ['A-W01', 'A-W02'], 'request_id': 'integration-same-key'}
            one = client.post('/api/admin/center/collections', json=payload)
            self.assertEqual(one.status_code, 200, one.text)
            cid = one.json()['collection_id']
            self.assertEqual(client.post('/api/admin/center/collections', json=payload).json()['collection_id'], cid)
            partial = client.post(f'/api/admin/center/collections/{cid}/arrivals', json={'item_ids': ['A-W01']}).json()
            self.assertEqual(partial['missing_item_ids'], ['A-W02'])
            self.assertIsNone(partial['arrived_at'])
            bad = client.post(f'/api/admin/center/collections/{cid}/arrivals', json={'item_ids': ['S-W01']})
            self.assertEqual(bad.status_code, 409)
            done = client.post(f'/api/admin/center/collections/{cid}/arrivals', json={'item_ids': ['A-W02']}).json()
            client.post(f'/api/admin/center/collections/{cid}/arrivals', json={'item_ids': ['A-W02']})
            self.assertTrue(done['arrived_at'])
            self.assertEqual(store.dashboard()['alerts'], [])
            self.assertEqual(store.dashboard()['event_count'], 4)
            self.assertEqual(client.post('/api/admin/center/demo/reset', json={}).status_code, 404)


class ReadinessTests(unittest.TestCase):
    def connection(self, rows):
        conn = MagicMock(); conn.__enter__.return_value = conn
        conn.cursor.return_value.__enter__.return_value.fetchone.side_effect = rows
        return conn

    def test_missing_or_unavailable_configuration_is_not_ready(self):
        self.assertFalse(check_readiness(None, None)['ready'])
        def fail(): raise RuntimeError('private-connection-details')
        r = check_readiness(fail, fail)
        self.assertFalse(r['ready']); self.assertNotIn('private', str(r))

    def test_schema_and_private_table_permissions_are_checked_read_only(self):
        write = self.connection([('collection', 'member', 'alert', 'log'), (True,), ('127.0.0.1', 5432, 'synthetic-db')])
        read = self.connection([(True, False, False, False), ('127.0.0.1', 5432, 'synthetic-db')])
        self.assertTrue(check_readiness(lambda: write, lambda: read)['ready'])
        for conn in (write, read):
            calls = conn.cursor.return_value.__enter__.return_value.execute.call_args_list
            self.assertEqual(calls[0].args[0], 'SET TRANSACTION READ ONLY')
            self.assertFalse(any(c.args[0].startswith(('INSERT', 'UPDATE', 'ALTER', 'CREATE')) for c in calls))
        unsafe = self.connection([(True, False, True, False), ('127.0.0.1', 5432, 'synthetic-db')])
        self.assertEqual(check_readiness(None, lambda: unsafe)['statistics'], 'unsafe_permissions')

    def test_different_read_database_is_not_reported_ready(self):
        write = self.connection([('collection', 'member', 'alert', 'log'), (True,), ('127.0.0.1', 5432, 'one')])
        read = self.connection([(True, False, False, False), ('127.0.0.1', 5432, 'other')])
        self.assertFalse(check_readiness(lambda: write, lambda: read)['ready'])
