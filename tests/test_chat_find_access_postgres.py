"""명시한 폐기용 lf_chat_access_test DB에서만 실행하는 PostgreSQL 통합 시험."""
from datetime import datetime, timedelta, timezone
import os
import unittest
import uuid

from agents.chat_find_auth import FindSessionAuth
from agents.chat_operations import Owner, binding_digest, owner_scope
from agents.chat_postgres_access import PostgresFindSessions, PostgresOperationResults, PostgresAccessUnavailable


DSN = os.environ.get('LF_CHAT_ACCESS_TEST_DSN', '')
KEY = b'synthetic-postgres-test-key-at-least-32-bytes'
TOKEN = 'synthetic-postgres-test-token'
OWNER = Owner('synthetic-subject', 'synthetic-auth-session')
OP_ID = 'op_' + 'd' * 32


@unittest.skipUnless(DSN, '폐기용 PostgreSQL LF_CHAT_ACCESS_TEST_DSN이 없어 제외')
class LivePostgresFindAccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(DSN).get('dbname') != 'lf_chat_access_test':
            raise RuntimeError('Only the disposable lf_chat_access_test database is allowed')
        cls.schema = 'chat_access_test_' + uuid.uuid4().hex
        with psycopg.connect(DSN) as db:
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(cls.schema)))
        def cleanup():
            with psycopg.connect(DSN) as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(cls.schema)))
        cls.addClassCleanup(cleanup)
        def connect(dsn, **kwargs):
            return psycopg.connect(dsn, options=f'-c search_path={cls.schema}', **kwargs)
        cls.connect = staticmethod(connect)
        now = datetime.now(timezone.utc)
        with connect(DSN) as db:
            db.execute('''CREATE TABLE chat_find_session_access (
                token_hash text PRIMARY KEY, subject_id text, auth_session_id text, expires_at timestamptz,
                id_verified_at timestamptz, consented_at timestamptz, revoked_at timestamptz, permissions text[])''')
            db.execute('INSERT INTO chat_find_session_access VALUES (%s,%s,%s,%s,%s,%s,NULL,%s)',
                       (binding_digest(KEY, 'find-token-v1', TOKEN), OWNER.subject, OWNER.auth_session,
                        now + timedelta(minutes=10), now, now,
                        ['chat:use', 'chat:search', 'chat:operations:read']))
            db.execute('''CREATE TABLE chat_operation_receipt_access (
                operation_id text PRIMARY KEY, owner_scope text, kind text,
                request_hash text, state text, result jsonb)''')
            db.execute('INSERT INTO chat_operation_receipt_access VALUES (%s,%s,%s,%s,%s,%s::jsonb)',
                       (OP_ID, owner_scope(KEY, OWNER), 'found', 'e' * 64, 'uncertain', '{}'))
        cls.auth = FindSessionAuth(PostgresFindSessions(DSN, connect).lookup, KEY)
        cls.results = PostgresOperationResults(DSN, KEY, connect)

    def test_real_auth_query_and_revocation(self):
        self.assertTrue(self.auth.authorize(TOKEN))
        with self.connect(DSN) as db:
            db.execute('UPDATE chat_find_session_access SET revoked_at=now()')
        try:
            self.assertFalse(self.auth.authorize(TOKEN))
        finally:
            with self.connect(DSN) as db:
                db.execute('UPDATE chat_find_session_access SET revoked_at=NULL')

    def test_real_owner_bound_receipt_query(self):
        from agents.chat_operations import OperationNotFound
        self.assertEqual(self.results.get(OWNER, OP_ID).state, 'uncertain')
        with self.assertRaises(OperationNotFound):
            self.results.get(Owner('other-owner', OWNER.auth_session), OP_ID)

    def test_adapter_transaction_rejects_actual_sql_write(self):
        with self.assertRaises(PostgresAccessUnavailable):
            self.results._query("UPDATE chat_operation_receipt_access SET state='completed'", ())
        self.assertEqual(self.results.get(OWNER, OP_ID).state, 'uncertain')
