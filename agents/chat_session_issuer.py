"""서버 내부 본인인증 세션 발급기. HTTP/클라이언트의 인증 완료 주장은 받지 않는다.

신뢰된 본인인증 결과·동의 조회 콜백을 명시 주입해야 한다. 자동 활성화/DDL 실행은 없다.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
import secrets
import time

from agents.chat_find_auth import PERMISSIONS
from agents.chat_operations import Owner, binding_digest


class SessionIssuanceRejected(PermissionError):
    pass


class SessionIssuanceUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, repr=False)
class IdentityProof:
    subject_id: str
    proof_id: str
    verified_at: float
    expires_at: float
    purpose: str


@dataclass(frozen=True, repr=False)
class RequiredConsent:
    subject_id: str
    policy_version: str
    consented_at: float
    accepted: bool
    revoked: bool


@dataclass(frozen=True, repr=False)
class SessionRecord:
    owner: Owner
    token_hash: str
    proof_hash: str
    issued_at: float
    expires_at: float
    verified_at: float
    consented_at: float
    policy_version: str
    permissions: frozenset[str]


@dataclass(frozen=True, repr=False)
class IssuedFindSession:
    owner: Owner
    access_token: str = field(repr=False)
    expires_at: float


def _opaque(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,128}', value) is not None


def _instant(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


class FindSessionIssuer:
    """발급·철회는 서버 내부 호출만 허용한다. 개인정보 원문/확인 토큰을 저장하지 않는다.

    verify_identity(proof_ref), lookup_consent(subject_id, consent_ref)는 실제 권위 저장소를 조회해야 한다.
    dict/True/가린 값에서 증거 객체를 만들어 주는 어댑터는 실제 본인인증 연결이 아니다.
    """

    def __init__(self, store, binding_key, *, verify_identity, lookup_consent, policy_version,
                 ttl_seconds, proof_max_age_seconds, permissions, clock=time.time):
        binding_digest(binding_key, 'validate-key', None)
        if not callable(verify_identity) or not callable(lookup_consent):
            raise ValueError('trusted identity and consent lookups are required')
        if not isinstance(policy_version, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', policy_version):
            raise ValueError('an explicit consent policy version is required')
        for value in (ttl_seconds, proof_max_age_seconds):
            if type(value) is not int or not 1 <= value <= 86400:
                raise ValueError('explicit lifetimes of 1..86400 seconds are required')
        if type(permissions) is not frozenset or not permissions or not permissions <= PERMISSIONS:
            raise ValueError('explicit server permissions are required')
        self._store, self._key = store, binding_key
        self._verify, self._consent, self._clock = verify_identity, lookup_consent, clock
        self._policy, self._ttl, self._proof_age = policy_version, ttl_seconds, proof_max_age_seconds
        self._permissions = permissions

    def __repr__(self):
        return 'FindSessionIssuer(credentials=***)'

    def _evidence(self, proof_ref, consent_ref):
        proof = self._verify(proof_ref)
        now = self._clock()
        valid = (type(proof) is IdentityProof and _opaque(proof.subject_id) and _opaque(proof.proof_id)
                 and proof.purpose == 'lostfound.find' and _instant(proof.verified_at)
                 and _instant(proof.expires_at) and _instant(now)
                 and 0 <= now - proof.verified_at <= self._proof_age and proof.expires_at > now)
        if not valid:
            raise SessionIssuanceRejected('본인인증·필수 동의 결과를 확인해주세요')
        consent = self._consent(proof.subject_id, consent_ref)
        # 동의 조회가 늦어지는 동안 증거가 만료될 수 있어 조회 뒤 시각으로 다시 판단한다.
        now = self._clock()
        valid = (_instant(now) and 0 <= now - proof.verified_at <= self._proof_age
                 and proof.expires_at > now and type(consent) is RequiredConsent
                 and consent.subject_id == proof.subject_id
                 and consent.policy_version == self._policy and consent.accepted is True
                 and consent.revoked is False and _instant(consent.consented_at)
                 and consent.consented_at <= now)
        if not valid:
            raise SessionIssuanceRejected('본인인증·필수 동의 결과를 확인해주세요')
        return proof, consent, now

    def issue(self, proof_ref, consent_ref):
        if not _opaque(proof_ref) or not _opaque(consent_ref):
            raise SessionIssuanceRejected('본인인증·필수 동의 결과를 확인해주세요')
        try:
            proof, consent, now = self._evidence(proof_ref, consent_ref)
            token = secrets.token_urlsafe(32)
            owner = Owner(proof.subject_id, 'fs_' + secrets.token_urlsafe(24))
            record = SessionRecord(owner, binding_digest(self._key, 'find-token-v1', token),
                                   binding_digest(self._key, 'find-proof-v1', [proof.subject_id, proof.proof_id]),
                                   now, now + self._ttl, proof.verified_at, consent.consented_at,
                                   self._policy, self._permissions)
            def validate_before_write():
                # 철회와 같은 사용자 잠금을 잡은 뒤 권위 원본을 다시 확인한다.
                fresh_proof, fresh_consent, current = self._evidence(proof_ref, consent_ref)
                if fresh_proof != proof or fresh_consent != consent or current >= record.expires_at:
                    raise SessionIssuanceRejected('인증 결과가 변경되었거나 만료되었습니다')
            if self._store.create(record, validate_before_write=validate_before_write) is not True:
                raise SessionIssuanceRejected('이미 사용한 본인인증 결과입니다. 다시 인증해주세요')
            return IssuedFindSession(owner, token, record.expires_at)
        except SessionIssuanceRejected:
            raise SessionIssuanceRejected('본인인증·필수 동의 결과를 확인해주세요') from None
        except Exception:
            raise SessionIssuanceUnavailable('인증 세션을 발급하지 못했습니다') from None

    def revoke(self, owner):
        if not isinstance(owner, Owner):
            raise ValueError('a server authenticated Owner is required')
        try:
            return self._store.revoke(owner, self._clock())
        except Exception:
            raise SessionIssuanceUnavailable('인증 세션을 철회하지 못했습니다') from None

    def revoke_subject(self, subject_id):
        """본인인증/필수 동의 철회 이벤트를 처리하는 서버 전용 입구."""
        if not _opaque(subject_id):
            raise ValueError('an opaque server subject is required')
        try:
            return self._store.revoke_subject(subject_id, self._clock())
        except Exception:
            raise SessionIssuanceUnavailable('인증 세션을 철회하지 못했습니다') from None


SQL_CREATE_SESSION = '''INSERT INTO lf_chat_security.find_session
    (token_hash, proof_hash, subject_id, auth_session_id, issued_at, expires_at,
     id_verified_at, consented_at, consent_policy_version, permissions)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (proof_hash) DO NOTHING RETURNING auth_session_id'''
SQL_REVOKE_SESSION = '''UPDATE lf_chat_security.find_session SET revoked_at=%s
WHERE subject_id=%s AND auth_session_id=%s AND revoked_at IS NULL RETURNING auth_session_id'''
SQL_REVOKE_SUBJECT = '''UPDATE lf_chat_security.find_session SET revoked_at=%s
WHERE subject_id=%s AND revoked_at IS NULL RETURNING auth_session_id'''
SQL_LOCK_SUBJECT = 'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))'


class PostgresFindSessionWriter:
    """명시한 쓰기 전용 연결로만 저장/철회. 인증 검증기의 SELECT 계정과 분리한다."""

    def __init__(self, dsn, connect=None):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError('an explicit session writer connection is required')
        self._dsn, self._connect = dsn, connect

    def __repr__(self):
        return 'PostgresFindSessionWriter(dsn=***)'

    def _write(self, sql, params, *, subject, validate_before_write=None):
        try:
            import psycopg
            connect = self._connect or psycopg.connect
            with connect(self._dsn, connect_timeout=5) as db:
                db.autocommit = False
                with db.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '3000ms'")
                    cur.execute(SQL_LOCK_SUBJECT, ('lf-chat-session:' + subject,))
                    if validate_before_write is not None:
                        validate_before_write()
                    cur.execute(sql, params)
                    rows = cur.fetchall()
            return rows
        except SessionIssuanceRejected:
            raise
        except Exception:
            raise SessionIssuanceUnavailable('인증 세션 저장소를 확인하지 못했습니다') from None

    @staticmethod
    def _timestamp(value):
        return datetime.fromtimestamp(value, timezone.utc)

    def create(self, record, *, validate_before_write):
        rows = self._write(SQL_CREATE_SESSION, (record.token_hash, record.proof_hash,
            record.owner.subject, record.owner.auth_session, self._timestamp(record.issued_at),
            self._timestamp(record.expires_at), self._timestamp(record.verified_at),
            self._timestamp(record.consented_at), record.policy_version, sorted(record.permissions)),
            subject=record.owner.subject, validate_before_write=validate_before_write)
        return len(rows) == 1 and rows[0][0] == record.owner.auth_session

    def revoke(self, owner, now):
        return bool(self._write(SQL_REVOKE_SESSION, (self._timestamp(now), owner.subject, owner.auth_session),
                                subject=owner.subject))

    def revoke_subject(self, subject_id, now):
        return len(self._write(SQL_REVOKE_SUBJECT, (self._timestamp(now), subject_id), subject=subject_id))
