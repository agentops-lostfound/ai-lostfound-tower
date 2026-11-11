from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agents.chat_find_auth import FindSessionAuth, PERMISSIONS
from agents.chat_operations import binding_digest
from agents.chat_postgres_access import PostgresFindSessions
from agents.chat_identity_evidence import (
    PostgresIdentityEvidence, PostgresEvidenceWriter, build_evidence_backed_issuer,
    EvidenceRejected, SQL_READ_PROOF, SQL_LOCK_PROOF, SQL_CURRENT_POLICY,
)
from agents.chat_session_issuer import IdentityProof, SessionIssuanceRejected, SessionIssuanceUnavailable, SQL_LOCK_SUBJECT
from identity_evidence_fixture import EvidenceDatabase


KEY = b'fictional-evidence-key-at-least-32-bytes-long'
SUBJECT = 'fictional-subject'


class IdentityEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'evidence.sqlite'
        self.db = EvidenceDatabase(self.path)
        self.now = 1000
        self.proof = IdentityProof(SUBJECT, 'fictional-proof-1', 990, 1100, 'lostfound.find')
        self.writer = self.make_writer()
        self.reader = PostgresIdentityEvidence('fake-reader', KEY,
            trusted_providers=frozenset({'trusted-test-provider'}), connect=self.db.connect)
        self.issuer = self.make_issuer()
        self.auth = FindSessionAuth(PostgresFindSessions('fake-auth', self.db.connect).lookup,
                                    KEY, clock=lambda: self.now)

    def make_writer(self, assurance='verified'):
        return PostgresEvidenceWriter('fake-writer', KEY, provider='trusted-test-provider',
            assurance=assurance, connect=self.db.connect, clock=lambda: self.now)

    def make_issuer(self):
        return build_evidence_backed_issuer(read_dsn='fake-reader', write_dsn='fake-writer', binding_key=KEY,
            trusted_providers=frozenset({'trusted-test-provider'}), policy_version='policy-v1',
            ttl_seconds=600, proof_max_age_seconds=60, permissions=PERMISSIONS,
            clock=lambda: self.now, read_connect=self.db.connect, write_connect=self.db.connect)

    def evidence(self, *, accepted=True, writer=None):
        writer = writer or self.writer
        proof_ref = writer.record_identity(self.proof)
        consent_ref = writer.record_consent(proof_ref, 'policy-v1', accepted)
        return proof_ref, consent_ref

    def issued(self):
        refs = self.evidence()
        return self.issuer.issue(*refs), refs

    def test_persisted_evidence_to_issuer_to_existing_session_verifier(self):
        issued, refs = self.issued()
        self.assertTrue(self.auth.authorize(issued.access_token))
        self.assertEqual(self.reader.verify_identity(refs[0]), self.proof)
        self.assertEqual(self.reader.lookup_consent(SUBJECT, refs[1]).policy_version, 'policy-v1')
        restarted = FindSessionAuth(PostgresFindSessions('fake-auth', self.db.connect).lookup, KEY, clock=lambda: self.now)
        self.assertEqual(restarted.require(issued.access_token).owner, issued.owner)

    def test_consent_withdrawal_invalidates_existing_token_without_session_revoke_event(self):
        issued, refs = self.issued()
        self.assertTrue(self.writer.revoke_consent(SUBJECT, refs[1]))
        self.assertFalse(self.auth.authorize(issued.access_token))
        self.assertEqual(self.db.count('sessions'), 1)  # 기록을 지워서 막은 것이 아님

    def test_identity_withdrawal_invalidates_existing_token_without_session_revoke_event(self):
        issued, refs = self.issued()
        self.assertTrue(self.writer.revoke_identity(SUBJECT, refs[0]))
        self.assertFalse(self.auth.authorize(issued.access_token))
        self.assertIsNone(self.reader.verify_identity(refs[0]))

    def test_current_policy_change_invalidates_old_consent_and_existing_token(self):
        issued, refs = self.issued()
        self.db.change("UPDATE policy SET version='policy-v2'")
        self.assertFalse(self.auth.authorize(issued.access_token))
        self.assertIsNone(self.reader.lookup_consent(SUBJECT, refs[1]))
        with self.assertRaises(SessionIssuanceRejected):
            self.make_issuer().issue(*refs)

    def test_disabled_provider_invalidates_existing_token_and_evidence(self):
        issued, refs = self.issued()
        self.db.change('UPDATE providers SET active=0')
        self.assertFalse(self.auth.authorize(issued.access_token))
        self.assertIsNone(self.reader.verify_identity(refs[0]))

    def test_simulation_evidence_cannot_issue_verified_session(self):
        refs = self.evidence(writer=self.make_writer('simulation'))
        self.assertIsNone(self.reader.verify_identity(refs[0]))
        with self.assertRaises(SessionIssuanceRejected):
            self.issuer.issue(*refs)
        self.assertEqual(self.db.count('sessions'), 0)

    def test_non_allowlisted_provider_is_not_trusted(self):
        refs = self.evidence()
        reader = PostgresIdentityEvidence('fake', KEY, trusted_providers=frozenset({'other-provider'}), connect=self.db.connect)
        self.assertIsNone(reader.verify_identity(refs[0]))

    def test_consent_denial_is_recorded_but_does_not_grant_a_session(self):
        refs = self.evidence(accepted=False)
        self.assertFalse(self.reader.lookup_consent(SUBJECT, refs[1]).accepted)
        with self.assertRaises(SessionIssuanceRejected):
            self.issuer.issue(*refs)
        self.assertEqual(self.db.count('consents'), 1)
        self.assertEqual(self.db.count('sessions'), 0)

    def test_consent_reference_cannot_be_used_for_another_subject(self):
        refs = self.evidence()
        self.assertIsNone(self.reader.lookup_consent('another-subject', refs[1]))
        self.proof = replace(self.proof, subject_id='another-subject', proof_id='another-proof-1')
        another_ref = self.writer.record_identity(self.proof)
        with self.assertRaises(SessionIssuanceRejected):
            self.issuer.issue(another_ref, refs[1])

    def test_other_subject_cannot_revoke_original_evidence(self):
        issued, refs = self.issued()
        self.assertFalse(self.writer.revoke_identity('another-subject', refs[0]))
        self.assertFalse(self.writer.revoke_consent('another-subject', refs[1]))
        self.assertTrue(self.auth.authorize(issued.access_token))

    def test_repeated_identity_is_immutable_and_does_not_replace_reference(self):
        refs = self.evidence()
        with self.assertRaises(EvidenceRejected):
            self.writer.record_identity(replace(self.proof, expires_at=2000))
        self.assertEqual(self.reader.verify_identity(refs[0]), self.proof)
        self.assertEqual(self.db.count('proofs'), 1)

    def test_unknown_or_client_claimed_identity_cannot_create_a_consent(self):
        for reference in ('unknown-proof-reference', {'id_verified': True}, True):
            with self.assertRaises(EvidenceRejected):
                self.writer.record_consent(reference, 'policy-v1', True)
        self.assertEqual(self.db.count('consents'), 0)

    def test_raw_identity_claims_cannot_be_recorded_as_a_proof(self):
        for proof in (True, {'id_verified': True}, replace(self.proof, subject_id='홍*동'),
                      replace(self.proof, purpose='other-purpose'), replace(self.proof, expires_at=1000)):
            with self.assertRaises(EvidenceRejected):
                self.writer.record_identity(proof)
        self.assertEqual(self.db.count('proofs'), 0)

    def test_withdrawn_proof_cannot_create_new_consent(self):
        proof_ref = self.writer.record_identity(self.proof)
        self.writer.revoke_identity(SUBJECT, proof_ref)
        with self.assertRaises(EvidenceRejected):
            self.writer.record_consent(proof_ref, 'policy-v1', True)
        self.assertEqual(self.db.count('consents'), 0)

    def test_obsolete_policy_cannot_be_recorded_as_current_consent(self):
        proof_ref = self.writer.record_identity(self.proof)
        with self.assertRaises(EvidenceRejected):
            self.writer.record_consent(proof_ref, 'old-policy', True)
        self.assertEqual(self.db.count('consents'), 0)

    def test_expiry_while_waiting_for_current_policy_prevents_consent_write(self):
        proof_ref = self.writer.record_identity(self.proof)
        self.db.hook = lambda sql: setattr(self, 'now', 1100) if sql == SQL_CURRENT_POLICY else None
        with self.assertRaises(EvidenceRejected):
            self.writer.record_consent(proof_ref, 'policy-v1', True)
        self.assertEqual(self.db.count('consents'), 0)

    def test_expired_proof_after_issuance_does_not_shorten_an_already_issued_session(self):
        issued, _ = self.issued()
        self.now = 1200
        self.assertTrue(self.auth.authorize(issued.access_token))
        self.now = issued.expires_at
        self.assertFalse(self.auth.authorize(issued.access_token))

    def test_replayed_evidence_does_not_create_another_session_after_restart(self):
        issued, refs = self.issued()
        with self.assertRaises(SessionIssuanceRejected):
            self.make_issuer().issue(*refs)
        self.assertEqual(self.db.count('sessions'), 1)
        self.assertTrue(self.auth.authorize(issued.access_token))

    def test_lock_order_is_subject_before_proof_row_for_consent_and_revocation(self):
        self.evidence()
        sqls = [c[0] for c in self.db.calls]
        start = sqls.index(SQL_READ_PROOF)
        self.assertLess(sqls.index(SQL_LOCK_SUBJECT, start), sqls.index(SQL_LOCK_PROOF, start))
        self.assertTrue(all(not autocommit for _,_,_,autocommit in self.db.calls))

    def test_token_and_opaque_references_are_not_stored_as_plaintext(self):
        issued, refs = self.issued()
        with closing(sqlite3.connect(self.path)) as db:
            dump = '\n'.join(db.iterdump())
        for secret in (issued.access_token, *refs, KEY.decode()):
            self.assertNotIn(secret, dump)
        self.assertNotIn('fake-writer', repr(self.writer))

    def test_concurrent_consumption_of_persisted_evidence_issues_once(self):
        refs = self.evidence()
        def attempt(_):
            try:
                return self.make_issuer().issue(*refs)
            except SessionIssuanceRejected:
                return None
        with ThreadPoolExecutor(4) as pool:
            results = list(pool.map(attempt, range(8)))
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertEqual(self.db.count('sessions'), 1)

    def test_source_db_failure_is_sanitized_and_does_not_issue(self):
        refs = self.evidence()
        with patch.object(self.reader, '_connect', side_effect=RuntimeError('private-dsn-and-token')):
            from agents.chat_session_issuer import FindSessionIssuer
            issuer = FindSessionIssuer(self.issuer._store, KEY, verify_identity=self.reader.verify_identity,
                lookup_consent=self.reader.lookup_consent, policy_version='policy-v1', ttl_seconds=600,
                proof_max_age_seconds=60, permissions=PERMISSIONS, clock=lambda: self.now)
            with self.assertRaises(SessionIssuanceUnavailable) as caught:
                issuer.issue(*refs)
        self.assertNotIn('private-dsn-and-token', str(caught.exception))
        self.assertEqual(self.db.count('sessions'), 0)

    def test_http_auth_reflects_source_withdrawal_without_a_logout_call(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from agents.chat_api import add_chat_routes
        from agents.chat_search import SearchAgent
        from test_chat_find_access import Bot, CONTEXT
        class Items:
            mode='postgres'
            def search(self, *_): return []
        issued, refs = self.issued()
        app = FastAPI()
        add_chat_routes(app, Bot(SearchAgent(Items())), find_auth=self.auth)
        client = TestClient(app)
        headers = {'Authorization': 'Bearer ' + issued.access_token}
        body = {'question': '검정 지갑 찾아줘', 'search_context': CONTEXT}
        self.assertEqual(client.post('/chat/questions', headers=headers, json=body).status_code, 200)
        self.writer.revoke_consent(SUBJECT, refs[1])
        response = client.post('/chat/questions', headers=headers, json=body)
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(issued.access_token, response.text)


if __name__ == '__main__':
    unittest.main()
