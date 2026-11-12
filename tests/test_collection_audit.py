"""Ledger-only read audit with independent PostgreSQL corruption fixtures."""
import io
import json
import os
from contextlib import redirect_stdout
from datetime import datetime, timezone
import unittest
from unittest.mock import MagicMock, patch
from center.collection_audit import audit_collections, RULES
from tools.audit_collections import main


class AuditBoundaryTests(unittest.TestCase):
    def test_invalid_limit_never_connects(self):
        connect = MagicMock()
        for limit in (0, 201, True, '50', None):
            with self.assertRaises(ValueError): audit_collections(connect, limit)
        connect.assert_not_called()

    def test_unavailable_is_not_zero_issues_and_hides_connection_details(self):
        def fail(): raise RuntimeError('synthetic-private-connection')
        for connect in (None, fail):
            result = audit_collections(connect)
            self.assertFalse(result['completed'])
            self.assertIsNone(result['issue_count'])
            self.assertNotEqual(result['status'], 'ok')
            self.assertNotIn('synthetic-private', str(result))

    def test_exact_counts_bounded_safe_identifiers_and_read_only_snapshot(self):
        conn = MagicMock(); conn.__enter__.return_value = conn
        cur = conn.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value = (datetime.now(timezone.utc), 80, 100, 12, 3, 2, 1)
        cur.fetchall.side_effect = [[('empty_collection', 'error', 80)], [('empty_collection', 'error', 'unsafe private identifier', 1)]]
        r = audit_collections(lambda: conn, 1)
        self.assertEqual(r['issue_count'], 80)
        self.assertTrue(r['truncated'])
        self.assertNotIn('unsafe private', str(r))
        self.assertEqual(r['counts']['unreviewed_collections'], 2)
        calls = cur.execute.call_args_list
        self.assertEqual(calls[0].args[0], 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        self.assertTrue(all(c.args[0].startswith(('SET ', 'WITH ')) for c in calls))
        self.assertEqual(calls[-1].args[1]['sample_limit'], 1)

    def test_cli_exit_codes_and_no_apply_or_env_file(self):
        for status, total, exit_code in [('ok', 0, 0), ('attention', 2, 1), ('unavailable', None, 2)]:
            result = {'status': status, 'completed': total is not None, 'issue_count': total}
            with patch('tools.audit_collections.audit_collections', return_value=result), patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main([]), exit_code)
                self.assertEqual(json.loads(out.getvalue()), result)
        with redirect_stdout(io.StringIO()), patch('sys.stderr', io.StringIO()), self.assertRaises(SystemExit):
            main(['--apply'])


    def test_autocommit_does_not_silently_bypass_snapshot_transaction(self):
        conn = MagicMock(); conn.__enter__.return_value = conn; conn.autocommit = True
        self.assertFalse(audit_collections(lambda: conn)['completed'])
        conn.cursor.return_value.__enter__.return_value.execute.assert_not_called()


@unittest.skipUnless(os.environ.get('LF_SUPPORT_TEST_DSN'), 'disposable PostgreSQL not configured')
class CollectionAuditPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tests.test_center_postgres as fixture
        fixture.PostgresIntegration.setUpClass.__func__(cls)

    def setUp(self):
        import tests.test_center_postgres as fixture
        fixture.PostgresIntegration.setUp(self)

    def pickup(self):
        return self.store.pickup('KIOSK-A', ['A-W01', 'A-W02'], 'audit-request-001')['collection_id']

    def codes(self, result):
        self.assertTrue(result['completed'], result)
        return {row['code'] for row in result['summary']}

    def snapshot(self):
        with self.connect() as db:
            return tuple(db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in
                         ('item', 'collection', 'collection_item', 'collection_alert', 'item_status_log'))

    def test_normal_pickup_partial_complete_and_post_return_have_no_false_alarms(self):
        self.assertEqual(self.store.audit()['issue_count'], 0)
        cid = self.pickup()
        before = self.snapshot()
        result = self.store.audit()
        self.assertEqual(result['issue_count'], 0, result)
        self.assertEqual(result['counts']['unreviewed_collections'], 1)
        self.store.arrive(cid, ['A-W01'])
        self.assertEqual(self.store.audit()['issue_count'], 0)
        self.store.arrive(cid, ['A-W02'])
        for status in ('확인 중', '승인·수령 예약', '반환 중', '인계 대기', '인계 완료', '반환 보류'):
            with self.connect() as db:
                db.execute('UPDATE item SET status=%s', (status,))
            self.assertEqual(self.store.audit()['issue_count'], 0, status)
        self.assertEqual(before[0:3], self.snapshot()[0:3])

    def test_wrong_machine_and_pending_status_are_reported_without_mutation(self):
        self.pickup()
        with self.connect() as db:
            db.execute("UPDATE item SET machine_id='KIOSK-C',status='본센터 보관' WHERE item_id='A-W02'")
        before = self.snapshot()
        codes = self.codes(self.store.audit())
        self.assertTrue({'machine_mismatch', 'pending_status_mismatch'} <= codes)
        self.assertEqual(before, self.snapshot())

    def test_missing_alert_after_partial_review_and_invalid_alert_after_arrival(self):
        cid = self.pickup(); self.store.arrive(cid, ['A-W01'])
        with self.connect() as db: db.execute('DELETE FROM collection_alert')
        self.assertIn('missing_active_alert', self.codes(self.store.audit()))
        self.store.arrive(cid, ['A-W02'])
        with self.connect() as db:
            db.execute("INSERT INTO collection_alert(collection_id,item_id) VALUES(%s,'A-W02')", (cid,))
        self.assertIn('invalid_active_alert', self.codes(self.store.audit()))

    def test_completion_and_event_history_missing_are_detected(self):
        cid = self.pickup()
        with self.connect() as db:
            db.execute('UPDATE collection SET arrived_at=picked_at-interval \'1 second\' WHERE collection_id=%s', (cid,))
            db.execute('DELETE FROM item_status_log')
        self.assertTrue({'completion_mismatch', 'completion_before_pickup', 'missing_pickup_history'} <= self.codes(self.store.audit()))
        self.store.arrive(cid, ['A-W01', 'A-W02'])
        with self.connect() as db: db.execute("DELETE FROM item_status_log WHERE to_status='본센터 보관'")
        self.assertIn('missing_arrival_history', self.codes(self.store.audit()))

    def test_duplicate_open_memberships_are_errors_but_history_attribution_is_review(self):
        self.pickup()
        with self.connect() as db:
            cid = db.execute("INSERT INTO collection(machine_id,request_id) VALUES('KIOSK-A','audit-request-002') RETURNING collection_id").fetchone()[0]
            db.execute("INSERT INTO collection_item(collection_id,item_id) VALUES(%s,'A-W01')", (cid,))
        codes = self.codes(self.store.audit())
        self.assertTrue({'multiple_open_collections', 'multiple_collection_history'} <= codes)
        self.assertNotIn('missing_pickup_history', codes)

    def test_legacy_transit_is_review_and_missing_history_is_not_invented(self):
        with self.connect() as db: db.execute("UPDATE item SET status='회수 중' WHERE item_id='A-W01'")
        result = self.store.audit()
        self.assertEqual(result['error_count'], 0)
        self.assertEqual(result['review_count'], 1)
        self.assertIn('transit_without_open_collection', self.codes(result))

    def test_arrived_item_in_transit_is_not_treated_as_normal_post_arrival(self):
        cid = self.pickup(); self.store.arrive(cid, ['A-W01', 'A-W02'])
        with self.connect() as db: db.execute("UPDATE item SET status='회수 중' WHERE item_id='A-W01'")
        self.assertIn('arrived_status_mismatch', self.codes(self.store.audit()))

    def test_insufficient_database_role_returns_unavailable_instead_of_zero(self):
        self.pickup()
        def connect():
            db = self.connect(); db.execute('SET ROLE lf_stats_reader'); return db
        result = audit_collections(connect)
        self.assertFalse(result['completed'])
        self.assertIsNone(result['issue_count'])

    def test_orphan_imported_member_is_detected_in_disposable_corruption_fixture(self):
        cid = self.pickup()
        with self.connect() as db:
            # Only this guarded disposable DB and only this transaction connection.
            db.execute('SET session_replication_role=replica')
            try:
                db.execute("INSERT INTO collection_item(collection_id,item_id) VALUES(%s,'A-W99')", (cid,))
            finally:
                db.execute('SET session_replication_role=origin')
        self.assertIn('orphan_member', self.codes(self.store.audit()))

    def test_autocommit_connection_is_reported_incomplete(self):
        def connect():
            db = self.connect(); db.autocommit = True; return db
        self.assertFalse(audit_collections(connect)['completed'])

    def test_legacy_collection_without_request_key_skips_history(self):
        cid = self.pickup()
        with self.connect() as db:
            db.execute('UPDATE collection SET request_id=NULL WHERE collection_id=%s', (cid,))
            db.execute('DELETE FROM item_status_log')
        r = self.store.audit()
        self.assertEqual(r['issue_count'], 0)
        self.assertEqual(r['counts']['history_members_unchecked'], 2)

    def test_total_is_exact_when_samples_are_truncated(self):
        with self.connect() as db:
            for n in range(55):
                db.execute("INSERT INTO collection(machine_id,request_id) VALUES('KIOSK-A',%s)", ('empty-audit-'+str(n),))
        result = self.store.audit(5)
        self.assertEqual(result['issue_count'], 55)
        self.assertEqual(len(result['issues']), 5)
        self.assertTrue(result['truncated'])

    def test_column_limited_role_succeeds_without_contact_identity_or_features(self):
        self.pickup()
        with self.connect() as db:
            db.execute("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='lf_audit_test_reader') THEN CREATE ROLE lf_audit_test_reader NOLOGIN; END IF; END $$")
            db.execute('GRANT USAGE ON SCHEMA public TO lf_audit_test_reader')
            db.execute('GRANT SELECT ON collection,collection_item,collection_alert,item_status_log TO lf_audit_test_reader')
            db.execute('GRANT SELECT(item_id,machine_id,status) ON item TO lf_audit_test_reader')
        def connect():
            db = self.connect(); db.execute('SET ROLE lf_audit_test_reader'); return db
        result = audit_collections(connect)
        self.assertTrue(result['completed'], result)
        self.assertEqual(result['issue_count'], 0)

    def test_protected_http_audit_is_read_only_and_input_is_bounded(self):
        from agents.api import build_app
        from agents.admin_auth import AdminAuth
        from agents.service import TowerService, demo_backend_factory
        from fastapi.testclient import TestClient
        from discord_ops.reporter import Reporter
        self.pickup()
        app = build_app(TowerService(demo_backend_factory(), Reporter(dry_run=True)),
                        admin_auth=AdminAuth('synthetic-password', 'synthetic-secret'),
                        center_services={'collections': self.store})
        with TestClient(app, base_url='http://127.0.0.1') as client:
            self.assertEqual(client.get('/api/admin/center/audit').status_code, 401)
            client.post('/api/admin/login', json={'password': 'synthetic-password'})
            before = self.snapshot()
            self.assertEqual(client.get('/api/admin/center/audit').json()['issue_count'], 0)
            for value in ('0', '-1', '201', 'bad'):
                self.assertEqual(client.get('/api/admin/center/audit?sample_limit='+value).status_code, 422)
            self.assertEqual(client.post('/api/admin/center/audit', json={}).status_code, 405)
            self.assertEqual(before, self.snapshot())
