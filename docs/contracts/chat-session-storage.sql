-- LF-5 제안 DDL: 팀 DB 담당자 검토/명시 적용 전에는 실행하지 않는다.
-- 런타임/center 마이그레이션에서 자동 실행하지 않는다. 기존 테이블/뷰를 덮어쓰지 않는다.
-- 쓰기 계정은 인증 발급 서버 전용, 조회 계정에는 아래 읽기 뷰의 SELECT만 부여한다.

CREATE SCHEMA lf_chat_security;

-- 실제 인증 수집 부품과 정책을 승인한 서버 운영자만 등록/활성화한다. 기본 데이터는 넣지 않는다.
CREATE TABLE lf_chat_security.trusted_provider (
    provider VARCHAR(64) PRIMARY KEY CHECK (provider ~ '^[a-z0-9_-]{1,64}$'),
    active BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE lf_chat_security.policy_state (
    purpose VARCHAR(32) PRIMARY KEY CHECK (purpose = 'lostfound.find'),
    policy_version VARCHAR(64) NOT NULL
);

CREATE TABLE lf_chat_security.identity_proof (
    proof_hash TEXT PRIMARY KEY CHECK (proof_hash ~ '^[0-9a-f]{64}$'),
    proof_ref_hash TEXT UNIQUE NOT NULL CHECK (proof_ref_hash ~ '^[0-9a-f]{64}$'),
    subject_id VARCHAR(128) NOT NULL CHECK (subject_id ~ '^[A-Za-z0-9_-]{8,128}$'),
    proof_id VARCHAR(128) NOT NULL CHECK (proof_id ~ '^[A-Za-z0-9_-]{8,128}$'),
    verified_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    purpose VARCHAR(32) NOT NULL CHECK (purpose = 'lostfound.find'),
    provider VARCHAR(64) NOT NULL REFERENCES lf_chat_security.trusted_provider(provider),
    assurance VARCHAR(16) NOT NULL CHECK (assurance IN ('verified', 'simulation')),
    revoked_at TIMESTAMPTZ,
    UNIQUE (proof_hash, subject_id),
    CHECK (expires_at > verified_at)
);

CREATE TABLE lf_chat_security.required_consent (
    consent_ref_hash TEXT PRIMARY KEY CHECK (consent_ref_hash ~ '^[0-9a-f]{64}$'),
    subject_id VARCHAR(128) NOT NULL CHECK (subject_id ~ '^[A-Za-z0-9_-]{8,128}$'),
    policy_version VARCHAR(64) NOT NULL,
    consented_at TIMESTAMPTZ NOT NULL,
    accepted BOOLEAN NOT NULL,
    revoked_at TIMESTAMPTZ,
    UNIQUE (subject_id, policy_version, consented_at)
);

CREATE TABLE lf_chat_security.find_session (
    token_hash TEXT PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    proof_hash TEXT UNIQUE NOT NULL CHECK (proof_hash ~ '^[0-9a-f]{64}$'),
    subject_id VARCHAR(128) NOT NULL CHECK (subject_id ~ '^[A-Za-z0-9_-]{8,128}$'),
    auth_session_id VARCHAR(64) UNIQUE NOT NULL CHECK (auth_session_id ~ '^fs_[A-Za-z0-9_-]{32}$'),
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    id_verified_at TIMESTAMPTZ NOT NULL,
    consented_at TIMESTAMPTZ NOT NULL,
    consent_policy_version VARCHAR(64) NOT NULL,
    permissions TEXT[] NOT NULL,
    revoked_at TIMESTAMPTZ,
    CHECK (expires_at > issued_at),
    CHECK (id_verified_at <= issued_at),
    CHECK (consented_at <= issued_at),
    CHECK (cardinality(permissions) > 0),
    CHECK (permissions <@ ARRAY['chat:use', 'chat:search', 'chat:operations:read']::TEXT[]),
    FOREIGN KEY (proof_hash, subject_id) REFERENCES lf_chat_security.identity_proof(proof_hash, subject_id),
    FOREIGN KEY (subject_id, consent_policy_version, consented_at)
        REFERENCES lf_chat_security.required_consent(subject_id, policy_version, consented_at)
);

CREATE INDEX find_session_subject_idx ON lf_chat_security.find_session(subject_id);

-- agents/chat_postgres_access.py가 읽는 계약. 이름 충돌 시 담당자와 매핑을 먼저 합의한다.
CREATE VIEW public.chat_find_session_access AS
SELECT s.token_hash, s.subject_id, s.auth_session_id, s.expires_at,
       s.id_verified_at, s.consented_at, s.revoked_at, s.permissions
FROM lf_chat_security.find_session s
JOIN lf_chat_security.identity_proof p ON p.proof_hash=s.proof_hash AND p.subject_id=s.subject_id
    AND p.verified_at=s.id_verified_at
JOIN lf_chat_security.trusted_provider tp ON tp.provider=p.provider AND tp.active
JOIN lf_chat_security.required_consent c ON c.subject_id=s.subject_id
    AND c.policy_version=s.consent_policy_version AND c.consented_at=s.consented_at
JOIN lf_chat_security.policy_state ps ON ps.purpose='lostfound.find' AND ps.policy_version=c.policy_version
WHERE p.assurance='verified' AND p.revoked_at IS NULL AND c.accepted AND c.revoked_at IS NULL;

CREATE VIEW public.chat_identity_proof_access AS
SELECT p.proof_ref_hash, p.subject_id, p.proof_id, p.verified_at, p.expires_at,
       p.purpose, p.provider, p.assurance, p.revoked_at
FROM lf_chat_security.identity_proof p
JOIN lf_chat_security.trusted_provider tp ON tp.provider=p.provider AND tp.active;

CREATE VIEW public.chat_required_consent_access AS
SELECT c.consent_ref_hash, c.subject_id, c.policy_version, c.consented_at, c.accepted, c.revoked_at
FROM lf_chat_security.required_consent c
JOIN lf_chat_security.policy_state ps ON ps.purpose='lostfound.find' AND ps.policy_version=c.policy_version;
