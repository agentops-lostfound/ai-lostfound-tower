"""서버 인증 결과·필수 동의 원본 저장/조회. 공개 HTTP나 모델 도구로 노출하지 않는다.

IdentityProof를 만드는 실제 본인인증은 별도 신뢰된 부품의 책임이다.
simulation 결과는 보관 가능하지만 인증/세션 발급에는 사용할 수 없다.
"""
from datetime import datetime, timezone
import re
import secrets
import time

from agents.chat_operations import binding_digest
from agents.chat_postgres_access import _ReadOnlyPostgres, PostgresAccessUnavailable
from agents.chat_session_issuer import (IdentityProof, RequiredConsent, FindSessionIssuer,
    PostgresFindSessionWriter, _instant, _opaque, SQL_LOCK_SUBJECT)


SQL_IDENTITY = '''SELECT subject_id, proof_id, extract(epoch FROM verified_at)::double precision,
    extract(epoch FROM expires_at)::double precision, purpose, provider, assurance, revoked_at IS NOT NULL
FROM chat_identity_proof_access WHERE proof_ref_hash=%s LIMIT 2'''
SQL_CONSENT = '''SELECT c.subject_id, c.policy_version,
    extract(epoch FROM c.consented_at)::double precision, c.accepted, c.revoked_at IS NOT NULL
FROM chat_required_consent_access c WHERE c.consent_ref_hash=%s AND c.subject_id=%s LIMIT 2'''


class PostgresIdentityEvidence(_ReadOnlyPostgres):
    def __init__(self, dsn, binding_key, *, trusted_providers, connect=None):
        super().__init__(dsn, connect)
        binding_digest(binding_key, 'validate-key', None)
        if (type(trusted_providers) is not frozenset or not trusted_providers
                or not all(isinstance(p, str) and re.fullmatch(r'[a-z0-9_-]{1,64}', p)
                           for p in trusted_providers)):
            raise ValueError('explicit trusted identity providers are required')
        self._key, self._providers = binding_key, trusted_providers

    def verify_identity(self, proof_ref):
        if not _opaque(proof_ref):
            return None
        row = self._query(SQL_IDENTITY, (binding_digest(self._key, 'find-proof-ref-v1', proof_ref),))
        if row is None:
            return None
        try:
            subject, proof_id, verified, expires, purpose, provider, assurance, revoked = row
            if (provider not in self._providers or assurance != 'verified' or revoked is not False
                    or purpose != 'lostfound.find' or not _opaque(subject) or not _opaque(proof_id)
                    or not _instant(verified) or not _instant(expires) or expires <= verified):
                return None
            return IdentityProof(subject, proof_id, verified, expires, purpose)
        except Exception:
            raise PostgresAccessUnavailable('본인인증 원본을 확인하지 못했습니다') from None

    def lookup_consent(self, subject_id, consent_ref):
        if not _opaque(subject_id) or not _opaque(consent_ref):
            return None
        row = self._query(SQL_CONSENT, (binding_digest(self._key, 'find-consent-v1', [subject_id, consent_ref]), subject_id))
        if row is None:
            return None
        try:
            subject, policy, consented_at, accepted, revoked = row
            if subject != subject_id or type(accepted) is not bool or type(revoked) is not bool or not _instant(consented_at):
                raise ValueError('invalid consent record')
            return RequiredConsent(subject, policy, consented_at, accepted, revoked)
        except Exception:
            raise PostgresAccessUnavailable('필수 동의 원본을 확인하지 못했습니다') from None


SQL_STORE_PROOF = '''INSERT INTO lf_chat_security.identity_proof
    (proof_hash,proof_ref_hash,subject_id,proof_id,verified_at,expires_at,purpose,provider,assurance)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (proof_hash) DO NOTHING RETURNING proof_id'''
SQL_LOCK_PROOF = '''SELECT subject_id,proof_id,verified_at,expires_at,purpose,provider,assurance,revoked_at
FROM lf_chat_security.identity_proof WHERE proof_ref_hash=%s FOR SHARE'''
SQL_READ_PROOF = SQL_LOCK_PROOF.removesuffix(' FOR SHARE')
SQL_CURRENT_POLICY = '''SELECT policy_version FROM lf_chat_security.policy_state
WHERE purpose='lostfound.find' FOR SHARE'''
SQL_STORE_CONSENT = '''INSERT INTO lf_chat_security.required_consent
    (consent_ref_hash,subject_id,policy_version,consented_at,accepted)
VALUES (%s,%s,%s,%s,%s) RETURNING consent_ref_hash'''
SQL_REVOKE_PROOF = '''UPDATE lf_chat_security.identity_proof SET revoked_at=%s
WHERE proof_ref_hash=%s AND subject_id=%s AND revoked_at IS NULL RETURNING proof_id'''
SQL_REVOKE_CONSENT = '''UPDATE lf_chat_security.required_consent SET revoked_at=%s
WHERE consent_ref_hash=%s AND subject_id=%s AND revoked_at IS NULL RETURNING consent_ref_hash'''


class EvidenceRejected(PermissionError):
    pass


class PostgresEvidenceWriter:
    """검증된 서버 이벤트만 전달하는 내부 저장 부품. provider/assurance는 서버 구성에서 고정한다.

    브라우저/모델의 입력을 IdentityProof로 바꾸어 이 부품을 호출하면 안 된다.
    실제 인증 결과 수집 어댑터가 없는 기본 앱에는 연결하지 않는다.
    """

    def __init__(self, dsn, binding_key, *, provider, assurance, connect=None, clock=time.time):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError('an explicit evidence writer connection is required')
        if not isinstance(provider, str) or not re.fullmatch(r'[a-z0-9_-]{1,64}', provider):
            raise ValueError('a server identity provider is required')
        if assurance not in ('verified', 'simulation'):
            raise ValueError('an explicit evidence assurance is required')
        binding_digest(binding_key, 'validate-key', None)
        self._dsn, self._key, self._provider, self._assurance = dsn, binding_key, provider, assurance
        self._connect, self._clock = connect, clock

    def __repr__(self):
        return 'PostgresEvidenceWriter(dsn=***, credentials=***)'

    def _connection(self):
        import psycopg
        return (self._connect or psycopg.connect)(self._dsn, connect_timeout=5)

    @staticmethod
    def _timestamp(value):
        return datetime.fromtimestamp(value, timezone.utc)

    @staticmethod
    def _begin(db, cur):
        cur.execute("SET LOCAL statement_timeout = '3000ms'")

    def record_identity(self, proof):
        now = self._clock()
        if (type(proof) is not IdentityProof or not _opaque(proof.subject_id) or not _opaque(proof.proof_id)
                or proof.purpose != 'lostfound.find' or not _instant(now)
                or not _instant(proof.verified_at) or not _instant(proof.expires_at)
                or proof.verified_at > now or proof.expires_at <= now):
            raise EvidenceRejected('본인인증 결과를 확인해주세요')
        reference = secrets.token_urlsafe(32)
        try:
            with self._connection() as db:
                db.autocommit = False
                with db.cursor() as cur:
                    self._begin(db, cur)
                    cur.execute(SQL_LOCK_SUBJECT, ('lf-chat-session:' + proof.subject_id,))
                    current = self._clock()
                    if not _instant(current) or proof.verified_at > current or proof.expires_at <= current:
                        raise EvidenceRejected('본인인증 결과가 만료되었습니다')
                    cur.execute(SQL_STORE_PROOF, (
                        binding_digest(self._key, 'find-proof-v1', [proof.subject_id, proof.proof_id]),
                        binding_digest(self._key, 'find-proof-ref-v1', reference), proof.subject_id, proof.proof_id,
                        self._timestamp(proof.verified_at), self._timestamp(proof.expires_at), proof.purpose,
                        self._provider, self._assurance))
                    if cur.fetchone() is None:
                        raise EvidenceRejected('이미 기록한 본인인증 결과입니다')
            return reference
        except EvidenceRejected:
            raise
        except Exception:
            raise PostgresAccessUnavailable('본인인증 결과를 저장하지 못했습니다') from None

    def record_consent(self, proof_ref, policy_version, accepted):
        if (not _opaque(proof_ref) or not isinstance(policy_version, str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', policy_version) or type(accepted) is not bool):
            raise EvidenceRejected('필수 동의 결과를 확인해주세요')
        reference = secrets.token_urlsafe(32)
        try:
            with self._connection() as db:
                db.autocommit = False
                with db.cursor() as cur:
                    self._begin(db, cur)
                    proof_hash = binding_digest(self._key, 'find-proof-ref-v1', proof_ref)
                    # 모든 쓰기가 사용자 잠금 → 원본 행 잠금 순서를 유지한다.
                    cur.execute(SQL_READ_PROOF, (proof_hash,))
                    initial = cur.fetchone()
                    if initial is None or not _opaque(initial[0]):
                        raise EvidenceRejected('본인인증 결과를 확인해주세요')
                    cur.execute(SQL_LOCK_SUBJECT, ('lf-chat-session:' + initial[0],))
                    cur.execute(SQL_LOCK_PROOF, (proof_hash,))
                    row = cur.fetchone()
                    now = self._clock()
                    if row is None:
                        raise EvidenceRejected('본인인증 결과를 확인해주세요')
                    subject, _, verified, expires, purpose, provider, assurance, revoked_at = row
                    if (subject != initial[0] or not _opaque(subject) or purpose != 'lostfound.find' or provider != self._provider
                            or assurance != self._assurance or revoked_at is not None
                            or not _instant(now) or verified.timestamp() > now or expires.timestamp() <= now):
                        raise EvidenceRejected('본인인증 결과를 확인해주세요')
                    cur.execute(SQL_CURRENT_POLICY)
                    policy = cur.fetchone()
                    if policy is None or policy[0] != policy_version:
                        raise EvidenceRejected('최신 필수 동의 정책을 확인해주세요')
                    now = self._clock()
                    if not _instant(now) or verified.timestamp() > now or expires.timestamp() <= now:
                        raise EvidenceRejected('본인인증 결과가 만료되었습니다')
                    cur.execute(SQL_STORE_CONSENT, (
                        binding_digest(self._key, 'find-consent-v1', [subject, reference]), subject,
                        policy_version, self._timestamp(now), accepted))
                    if cur.fetchone() is None:
                        raise PostgresAccessUnavailable('필수 동의 저장 결과를 확인하지 못했습니다')
            return reference
        except EvidenceRejected:
            raise
        except Exception:
            raise PostgresAccessUnavailable('필수 동의 결과를 저장하지 못했습니다') from None

    def _revoke(self, sql, subject_id, reference, domain):
        if not _opaque(subject_id) or not _opaque(reference):
            raise EvidenceRejected('서버 인증 기록을 확인해주세요')
        try:
            with self._connection() as db:
                db.autocommit = False
                with db.cursor() as cur:
                    self._begin(db, cur)
                    cur.execute(SQL_LOCK_SUBJECT, ('lf-chat-session:' + subject_id,))
                    value = reference if domain == 'find-proof-ref-v1' else [subject_id, reference]
                    cur.execute(sql, (self._timestamp(self._clock()), binding_digest(self._key, domain, value), subject_id))
                    changed = cur.fetchone() is not None
            return changed
        except Exception:
            raise PostgresAccessUnavailable('인증 기록을 철회하지 못했습니다') from None

    def revoke_identity(self, subject_id, proof_ref):
        return self._revoke(SQL_REVOKE_PROOF, subject_id, proof_ref, 'find-proof-ref-v1')

    def revoke_consent(self, subject_id, consent_ref):
        return self._revoke(SQL_REVOKE_CONSENT, subject_id, consent_ref, 'find-consent-v1')


def build_evidence_backed_issuer(*, read_dsn, write_dsn, binding_key, trusted_providers,
        policy_version, ttl_seconds, proof_max_age_seconds, permissions, clock=time.time,
        read_connect=None, write_connect=None):
    """검토된 서버 구성에서만 호출한다. 기존 앱이나 환경값에서 자동으로 켜지 않는다."""
    evidence = PostgresIdentityEvidence(read_dsn, binding_key,
        trusted_providers=trusted_providers, connect=read_connect)
    writer = PostgresFindSessionWriter(write_dsn, connect=write_connect)
    return FindSessionIssuer(writer, binding_key, verify_identity=evidence.verify_identity,
        lookup_consent=evidence.lookup_consent, policy_version=policy_version,
        ttl_seconds=ttl_seconds, proof_max_age_seconds=proof_max_age_seconds,
        permissions=permissions, clock=clock)
