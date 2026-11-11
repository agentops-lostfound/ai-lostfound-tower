-- LF-5 제안 DDL: 팀 DB 담당자 검토/명시 적용 전에는 실행하지 않는다.
-- 런타임/center 마이그레이션에서 자동 실행하지 않는다. 기존 테이블/뷰를 덮어쓰지 않는다.
-- 쓰기 계정은 인증 발급 서버 전용, 조회 계정에는 아래 읽기 뷰의 SELECT만 부여한다.

CREATE SCHEMA lf_chat_security;

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
    CHECK (permissions <@ ARRAY['chat:use', 'chat:search', 'chat:operations:read']::TEXT[])
);

CREATE INDEX find_session_subject_idx ON lf_chat_security.find_session(subject_id);

-- agents/chat_postgres_access.py가 읽는 계약. 이름 충돌 시 담당자와 매핑을 먼저 합의한다.
CREATE VIEW public.chat_find_session_access AS
SELECT token_hash, subject_id, auth_session_id, expires_at,
       id_verified_at, consented_at, revoked_at, permissions
FROM lf_chat_security.find_session;
