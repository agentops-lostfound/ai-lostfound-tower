"""폐기용 PostgreSQL에서 원본 DDL·인증/동의/세션 SQL을 검증한다.

LF_CHAT_ACCESS_TEST_DSN의 DB 이름이 lf_chat_access_test인 경우만 실행한다.
운영 이름 대신 UUID 시험 스키마를 사용하며 public/기존 표를 건드리지 않는다.
환경값이 없으면 제외한다. SQLite 대역 성공을 PostgreSQL 성공으로 표시하지 않는다.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch, MagicMock
import uuid

from agents.chat_find_auth import FindSessionAuth, PERMISSIONS
from agents.chat_identity_evidence import (
    PostgresEvidenceWriter, PostgresIdentityEvidence, EvidenceRejected, build_evidence_backed_issuer,
)
from agents.chat_postgres_access import PostgresFindSessions, PostgresAccessUnavailable
from agents.chat_session_issuer import IdentityProof, SessionIssuanceRejected

DSN = os.environ.get('LF_CHAT_ACCESS_TEST_DSN', '')
KEY = b'synthetic-native-postgres-identity-test-key'
PROVIDER = 'trusted-native-test-provider'


class NativePostgresTargetGuardTest(unittest.TestCase):
    def test_other_database_is_rejected_before_connecting(self):
        case = NativePostgresIdentityTest('test_exact_ddl_accepts_verified_evidence_and_authorizes_session')
        with patch(__name__ + '.DSN', 'dbname=production'), patch('psycopg.connect') as connect:
            with self.assertRaisesRegex(RuntimeError, 'Only the disposable'):
                case.setUp()
        connect.assert_not_called()

    def test_actual_database_name_is_checked_before_creating_schema(self):
        case = NativePostgresIdentityTest('test_exact_ddl_accepts_verified_evidence_and_authorizes_session')
        connection = MagicMock()
        connection.__enter__.return_value.execute.return_value.fetchone.return_value = ('other-database',)
        with patch(__name__ + '.DSN', 'dbname=lf_chat_access_test'), patch('psycopg.connect', return_value=connection):
            with self.assertRaisesRegex(RuntimeError, 'not the disposable'):
                case.setUp()
        db = connection.__enter__.return_value
        self.assertEqual(db.execute.call_count, 1)
        self.assertEqual(db.execute.call_args.args, ('SELECT current_database()',))


@unittest.skipUnless(DSN, '폐기용 PostgreSQL LF_CHAT_ACCESS_TEST_DSN이 없어 제외')
class NativePostgresIdentityTest(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import conninfo_to_dict
        if conninfo_to_dict(DSN).get('dbname') != 'lf_chat_access_test':
            raise RuntimeError('Only the disposable lf_chat_access_test database is allowed')
        self.schema = 'chat_identity_test_' + uuid.uuid4().hex
        with psycopg.connect(DSN) as db:
            if db.execute('SELECT current_database()').fetchone()[0] != 'lf_chat_access_test':
                raise RuntimeError('The connected database is not the disposable test database')
            db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(self.schema)))

        def cleanup():
            with psycopg.connect(DSN) as db:
                db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.schema)))
        self.addCleanup(cleanup)
        schema = self.schema

        class ScopedCursor(psycopg.Cursor):
            def execute(self, query, params=None, **kwargs):
                if isinstance(query, str):
                    query = query.replace('lf_chat_security.', schema + '.')
                return super().execute(query, params, **kwargs)

        def connect(dsn, **kwargs):
            return psycopg.connect(dsn, options='-c search_path=' + schema,
                                   cursor_factory=ScopedCursor, **kwargs)
        self.connect = connect
        ddl = (Path(__file__).resolve().parents[1] / 'docs/contracts/chat-session-storage.sql').read_text(encoding='utf-8')
        # 표/제약/뷰/타입/잠금 SQL은 원본을 사용하고 이름 공간만 시험용으로 바꾼다.
        ddl = ddl.replace('CREATE SCHEMA lf_chat_security;', '')
        ddl = ddl.replace('lf_chat_security.', schema + '.').replace('public.chat_', schema + '.chat_')
        with connect(DSN) as db:
            db.execute(ddl)
            db.execute('INSERT INTO trusted_provider(provider,active) VALUES (%s,TRUE)', (PROVIDER,))
            db.execute("INSERT INTO policy_state VALUES ('lostfound.find','policy-v1')")
        self.now = float(int(time.time()))
        self.subject = 'native_' + uuid.uuid4().hex
        self.writer = PostgresEvidenceWriter(DSN, KEY, provider=PROVIDER, assurance='verified',
                                             connect=connect, clock=lambda: self.now)
        self.reader = PostgresIdentityEvidence(DSN, KEY, trusted_providers=frozenset({PROVIDER}), connect=connect)
        self.auth = FindSessionAuth(PostgresFindSessions(DSN, connect).lookup, KEY, clock=lambda: self.now)

    def issuer(self):
        return build_evidence_backed_issuer(read_dsn=DSN, write_dsn=DSN, binding_key=KEY,
            trusted_providers=frozenset({PROVIDER}), policy_version='policy-v1', ttl_seconds=600,
            proof_max_age_seconds=60, permissions=PERMISSIONS, clock=lambda: self.now,
            read_connect=self.connect, write_connect=self.connect)

    def evidence(self, *, assurance='verified', accepted=True):
        writer = self.writer if assurance == 'verified' else PostgresEvidenceWriter(
            DSN, KEY, provider=PROVIDER, assurance=assurance, connect=self.connect, clock=lambda: self.now)
        proof = IdentityProof(self.subject, 'proof_' + uuid.uuid4().hex, self.now - 1, self.now + 120, 'lostfound.find')
        proof_ref = writer.record_identity(proof)
        consent_ref = writer.record_consent(proof_ref, 'policy-v1', accepted)
        return proof, proof_ref, consent_ref

    def test_exact_ddl_accepts_verified_evidence_and_authorizes_session(self):
        proof, proof_ref, consent_ref = self.evidence()
        self.assertEqual(self.reader.verify_identity(proof_ref), proof)
        issued = self.issuer().issue(proof_ref, consent_ref)
        owner = self.auth.require(issued.access_token).owner
        self.assertEqual(owner.subject, self.subject)
        self.assertEqual(owner.auth_session, issued.owner.auth_session)
        with self.connect(DSN) as db:
            row = db.execute('SELECT token_hash,proof_hash FROM find_session').fetchone()
        self.assertNotIn(issued.access_token, row)

    def test_simulation_is_stored_but_cannot_issue_or_authorize(self):
        _, proof_ref, consent_ref = self.evidence(assurance='simulation')
        self.assertIsNone(self.reader.verify_identity(proof_ref))
        with self.assertRaises(SessionIssuanceRejected):
            self.issuer().issue(proof_ref, consent_ref)

    def test_consent_denial_cannot_issue(self):
        _, proof_ref, consent_ref = self.evidence(accepted=False)
        with self.assertRaises(SessionIssuanceRejected):
            self.issuer().issue(proof_ref, consent_ref)

    def test_source_withdrawal_immediately_denies_existing_session(self):
        for source in ('identity', 'consent'):
            with self.subTest(source=source):
                self.subject = 'native_' + uuid.uuid4().hex
                _, proof_ref, consent_ref = self.evidence()
                issued = self.issuer().issue(proof_ref, consent_ref)
                self.assertTrue(self.auth.authorize(issued.access_token))
                revoke = self.writer.revoke_identity if source == 'identity' else self.writer.revoke_consent
                self.assertTrue(revoke(self.subject, proof_ref if source == 'identity' else consent_ref))
                self.assertFalse(self.auth.authorize(issued.access_token))

    def test_provider_disable_and_policy_change_deny_without_session_update(self):
        _, proof_ref, consent_ref = self.evidence()
        issued = self.issuer().issue(proof_ref, consent_ref)
        with self.connect(DSN) as db:
            db.execute('UPDATE trusted_provider SET active=FALSE')
        self.assertFalse(self.auth.authorize(issued.access_token))
        with self.connect(DSN) as db:
            db.execute('UPDATE trusted_provider SET active=TRUE')
        self.assertTrue(self.auth.authorize(issued.access_token))
        with self.connect(DSN) as db:
            db.execute("UPDATE policy_state SET policy_version='policy-v2'")
        self.assertFalse(self.auth.authorize(issued.access_token))

    def test_concurrent_proof_consumption_issues_exactly_once(self):
        _, proof_ref, consent_ref = self.evidence()
        def consume(_):
            try:
                return self.issuer().issue(proof_ref, consent_ref)
            except SessionIssuanceRejected:
                return None
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(consume, range(8)))
        self.assertEqual(sum(value is not None for value in results), 1)
        with self.connect(DSN) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM find_session').fetchone()[0], 1)

    def test_immutable_duplicate_proof_keeps_original_reference(self):
        proof, proof_ref, _ = self.evidence()
        with self.assertRaises(EvidenceRejected):
            self.writer.record_identity(replace(proof, expires_at=proof.expires_at + 60))
        self.assertEqual(self.reader.verify_identity(proof_ref), proof)

    def test_schema_constraints_reject_orphan_session(self):
        import psycopg
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            with self.connect(DSN) as db:
                db.execute('''INSERT INTO find_session
                    (token_hash,proof_hash,subject_id,auth_session_id,issued_at,expires_at,
                     id_verified_at,consented_at,consent_policy_version,permissions)
                    VALUES (%s,%s,%s,%s,now(),now()+interval '10 minutes',now(),now(),%s,%s)''',
                    ('a' * 64, 'b' * 64, self.subject, 'fs_' + 'c' * 32, 'policy-v1', ['chat:use']))

    def test_read_adapter_rejects_actual_write(self):
        self.evidence()
        with self.assertRaises(PostgresAccessUnavailable):
            self.reader._query('UPDATE lf_chat_security.trusted_provider SET active=FALSE', ())
        with self.connect(DSN) as db:
            self.assertIs(db.execute('SELECT active FROM trusted_provider').fetchone()[0], True)
