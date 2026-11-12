from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from agents.chat_find_auth import FindSessionAuth, FindAuthenticationRequired, PERMISSIONS
from agents.chat_operations import Owner, connection
from agents.chat_session_issuer import (
    FindSessionIssuer, IdentityProof, RequiredConsent, PostgresFindSessionWriter,
    SessionIssuanceRejected, SessionIssuanceUnavailable,
    SQL_LOCK_SUBJECT, SQL_CREATE_SESSION, SQL_REVOKE_SESSION, SQL_REVOKE_SUBJECT,
)
from session_issuer_fixture import SQLiteSessionStore


KEY = b'fictional-session-issuer-key-at-least-32-bytes'
PROOF_REF, CONSENT_REF = 'fictional-proof-reference', 'fictional-consent-reference'


class SessionIssuerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'session.sqlite'
        self.now = 1000
        self.proof = IdentityProof('fictional-subject', 'fictional-proof-1', 990, 1100, 'lostfound.find')
        self.consent = RequiredConsent('fictional-subject', 'policy-v1', 980, True, False)
        self.store = SQLiteSessionStore(self.path)
        self.verify = Mock(side_effect=lambda _: self.proof)
        self.consent_lookup = Mock(side_effect=lambda *_: self.consent)
        self.issuer = self.make_issuer()
        self.auth = FindSessionAuth(self.store.lookup, KEY, clock=lambda: self.now)

    def make_issuer(self, store=None):
        return FindSessionIssuer(store or self.store, KEY, verify_identity=self.verify,
            lookup_consent=self.consent_lookup, policy_version='policy-v1', ttl_seconds=600,
            proof_max_age_seconds=60, permissions=PERMISSIONS, clock=lambda: self.now)

    def issue(self):
        return self.issuer.issue(PROOF_REF, CONSENT_REF)

    def test_issue_roundtrip_through_existing_verifier_and_restart(self):
        issued = self.issue()
        self.assertEqual(len(issued.access_token), 43)
        self.assertEqual(issued.expires_at, 1600)
        self.assertEqual(self.auth.require(issued.access_token).owner, issued.owner)
        restarted = FindSessionAuth(SQLiteSessionStore(self.path).lookup, KEY, clock=lambda: self.now)
        self.assertTrue(restarted.authorize(issued.access_token))
        self.assertEqual(self.verify.call_count, 2)  # 저장 잠금 전과 후

    def test_token_proof_and_consent_references_never_persist_or_appear_in_repr(self):
        issued = self.issue()
        with connection(self.path) as db:
            dump = '\n'.join(db.iterdump())
        for secret in (issued.access_token, PROOF_REF, CONSENT_REF, self.proof.proof_id, KEY.decode()):
            self.assertNotIn(secret, dump)
            self.assertNotIn(secret, repr(issued) + repr(self.issuer))

    def test_same_identity_proof_is_single_use_after_restart_and_revocation(self):
        issued = self.issue()
        self.issuer.revoke(issued.owner)
        self.issuer = self.make_issuer(SQLiteSessionStore(self.path))
        with self.assertRaises(SessionIssuanceRejected):
            self.issue()
        self.assertEqual(self.store.count(), 1)

    def test_concurrent_issuance_consumes_proof_once(self):
        def attempt(_):
            try:
                return self.issue()
            except SessionIssuanceRejected:
                return None
        with ThreadPoolExecutor(6) as pool:
            results = list(pool.map(attempt, range(12)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(self.store.count(), 1)

    def test_expired_wrong_purpose_old_and_client_claimed_proofs_do_not_issue(self):
        for proof in (True, {'id_verified': True}, replace(self.proof, purpose='another-purpose'),
                      replace(self.proof, expires_at=1000), replace(self.proof, verified_at=1001),
                      replace(self.proof, verified_at=939), replace(self.proof, subject_id='홍*동'),
                      replace(self.proof, verified_at=float('nan'))):
            self.proof = proof
            with self.assertRaises(SessionIssuanceRejected):
                self.issue()
            # 다음 subtest의 기준을 원래 값으로 돌린다.
            self.proof = IdentityProof('fictional-subject', 'fictional-proof-1', 990, 1100, 'lostfound.find')
        self.assertEqual(self.store.count(), 0)

    def test_missing_mismatched_outdated_and_revoked_consent_do_not_issue(self):
        original = self.consent
        for consent in (None, True, {'consent': True}, replace(original, subject_id='another-subject'),
                        replace(original, policy_version='old-policy'), replace(original, accepted=1),
                        replace(original, revoked=True), replace(original, consented_at=1001)):
            self.consent = consent
            with self.assertRaises(SessionIssuanceRejected):
                self.issue()
        self.assertEqual(self.store.count(), 0)

    def test_no_token_is_issued_from_raw_identity_or_boolean_refs(self):
        for reference in (None, True, '홍*동', '******-1******', {'id_verified': True}):
            with self.assertRaises(SessionIssuanceRejected):
                self.issuer.issue(reference, CONSENT_REF)
        self.verify.assert_not_called()
        self.assertEqual(self.store.count(), 0)

    def test_revoked_or_changed_consent_before_write_rolls_back(self):
        self.consent_lookup.side_effect = [self.consent, replace(self.consent, revoked=True)]
        with self.assertRaises(SessionIssuanceRejected):
            self.issue()
        self.assertEqual(self.store.count(), 0)

    def test_expiration_between_validation_and_write_does_not_issue(self):
        calls = [0]
        def verify(_):
            calls[0] += 1
            if calls[0] == 2:
                self.now = 1200
            return self.proof
        self.verify.side_effect = verify
        with self.assertRaises(SessionIssuanceRejected):
            self.issue()
        self.assertEqual(self.store.count(), 0)

    def test_proof_expiring_during_consent_lookup_does_not_issue(self):
        def slow_consent(*_):
            self.now = self.proof.expires_at
            return self.consent
        self.consent_lookup.side_effect = slow_consent
        with self.assertRaises(SessionIssuanceRejected):
            self.issue()
        self.assertEqual(self.store.count(), 0)

    def test_single_session_revoke_does_not_revoke_another_session(self):
        first = self.issue()
        self.proof = replace(self.proof, proof_id='fictional-proof-2')
        second = self.issue()
        self.assertTrue(self.issuer.revoke(first.owner))
        self.assertFalse(self.issuer.revoke(first.owner))
        self.assertFalse(self.auth.authorize(first.access_token))
        self.assertTrue(self.auth.authorize(second.access_token))

    def test_subject_revocation_invalidates_all_sessions(self):
        first = self.issue()
        self.proof = replace(self.proof, proof_id='fictional-proof-2')
        second = self.issue()
        self.assertEqual(self.issuer.revoke_subject(first.owner.subject), 2)
        self.assertFalse(self.auth.authorize(first.access_token))
        self.assertFalse(self.auth.authorize(second.access_token))

    def test_revocation_during_issuance_does_not_leave_a_live_session(self):
        entered, release = threading.Event(), threading.Event()
        original = self.consent
        calls = [0]
        def consent_lookup(*_):
            calls[0] += 1
            if calls[0] == 2:
                entered.set()
                if not release.wait(10):
                    raise AssertionError('barrier timed out')
                return original  # 검증 직후 철회되는 경계를 재현
            return self.consent
        self.consent_lookup.side_effect = consent_lookup
        with ThreadPoolExecutor(2) as pool:
            issuing = pool.submit(self.issue)
            self.assertTrue(entered.wait(10))
            self.consent = replace(original, revoked=True)
            revoking = pool.submit(self.issuer.revoke_subject, original.subject_id)
            release.set()
            issued = issuing.result(10)
            self.assertEqual(revoking.result(10), 1)
        self.assertFalse(self.auth.authorize(issued.access_token))

    def test_session_expiry_and_wrong_key_fail_closed(self):
        issued = self.issue()
        self.now = issued.expires_at
        self.assertFalse(self.auth.authorize(issued.access_token))
        other = FindSessionAuth(self.store.lookup, b'different-test-key-at-least-32-bytes', clock=lambda: 1000)
        self.assertFalse(other.authorize(issued.access_token))

    def test_identity_and_storage_errors_are_sanitized(self):
        for failure in (RuntimeError('private-token-error'), SessionIssuanceRejected('private-token-error')):
            self.verify.side_effect = failure
            with self.assertRaises((SessionIssuanceUnavailable, SessionIssuanceRejected)) as caught:
                self.issue()
            self.assertNotIn('private-token-error', str(caught.exception))
        self.assertEqual(self.store.count(), 0)

    def test_response_loss_after_commit_does_not_duplicate_or_reveal_token(self):
        def failure():
            raise TimeoutError('private-commit-response')
        self.issuer = self.make_issuer(SQLiteSessionStore(self.path, after_commit=failure))
        with self.assertRaises(SessionIssuanceUnavailable) as caught:
            self.issue()
        self.assertNotIn('private-commit-response', str(caught.exception))
        self.issuer = self.make_issuer()
        with self.assertRaises(SessionIssuanceRejected):
            self.issue()
        self.assertEqual(self.store.count(), 1)

    def test_lifetimes_permissions_and_policy_must_be_explicit_server_settings(self):
        base = dict(verify_identity=self.verify, lookup_consent=self.consent_lookup, policy_version='policy-v1',
                    ttl_seconds=600, proof_max_age_seconds=60, permissions=PERMISSIONS)
        for override in ({'ttl_seconds': True}, {'ttl_seconds': 0}, {'proof_max_age_seconds': 86401},
                         {'permissions': frozenset({'admin'})}, {'permissions': set(PERMISSIONS)},
                         {'policy_version': ''}, {'verify_identity': None}):
            with self.assertRaises(ValueError):
                FindSessionIssuer(self.store, KEY, **{**base, **override})


class PostgresWriterTest(unittest.TestCase):
    def test_writes_use_same_subject_lock_before_revalidation_and_parameterized_sql(self):
        events = []
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def execute(self, sql, params=None):
                events.append((sql, params))
                self.sql, self.params = sql, params
            def fetchall(self):
                return [(self.params[3],)] if self.sql == SQL_CREATE_SESSION else [('session-1',)]
        class DB:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def cursor(self): return Cursor()
        writer = PostgresFindSessionWriter('private-dsn', connect=lambda *_, **__: DB())
        from agents.chat_session_issuer import SessionRecord
        owner = Owner('fictional-subject', 'fictional-session')
        record = SessionRecord(owner, 'a' * 64, 'b' * 64, 1000, 1600, 990, 980, 'policy-v1', PERMISSIONS)
        self.assertTrue(writer.create(record, validate_before_write=lambda: events.append(('validate', None))))
        self.assertEqual([e[0] for e in events], ["SET LOCAL statement_timeout = '3000ms'",
                                                 SQL_LOCK_SUBJECT, 'validate', SQL_CREATE_SESSION])
        self.assertNotIn(owner.subject, SQL_CREATE_SESSION)
        self.assertTrue(writer.revoke(owner, 1001))
        self.assertEqual(events[-1][0], SQL_REVOKE_SESSION)
        self.assertEqual(writer.revoke_subject(owner.subject, 1002), 1)
        self.assertEqual(events[-1][0], SQL_REVOKE_SUBJECT)
        self.assertNotIn('private-dsn', repr(writer))


if __name__ == '__main__':
    unittest.main()
