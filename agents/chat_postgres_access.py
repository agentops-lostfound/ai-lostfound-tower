"""운영 PostgreSQL의 서버 소유 인증/작업 영수증 읽기 연결. DDL/쓰기/토큰 발급 없음.

필요한 읽기 뷰 계약은 docs/contracts/chat-postgres-auth.md에 있다.
뷰가 없거나 연결에 실패하면 권한을 열지 않고 오류를 반환한다.
"""
import json
import re

from agents.chat_find_auth import FindSession, FindSessionAuth
from agents.chat_operations import (
    Owner, Operation, OperationJournal, OperationNotFound, STATES, binding_digest, owner_scope,
)


SQL_FIND_SESSION = '''SELECT subject_id, auth_session_id,
    extract(epoch FROM expires_at)::double precision,
    id_verified_at IS NOT NULL, consented_at IS NOT NULL, revoked_at IS NOT NULL, permissions
FROM chat_find_session_access WHERE token_hash = %s LIMIT 2'''
SQL_OPERATION_RECEIPT = '''SELECT operation_id, owner_scope, kind, request_hash, state, result
FROM chat_operation_receipt_access WHERE operation_id = %s AND owner_scope = %s LIMIT 2'''


class PostgresAccessUnavailable(RuntimeError):
    pass


class _ReadOnlyPostgres:
    def __init__(self, dsn, connect=None):
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError('a PostgreSQL connection must be explicitly configured')
        self._dsn, self._connect = dsn, connect

    def __repr__(self):
        return f'{type(self).__name__}(dsn=***)'

    def _query(self, sql, params):
        try:
            import psycopg
            connect = self._connect or psycopg.connect
            with connect(self._dsn, connect_timeout=5) as db:
                db.autocommit = False
                db.read_only = True
                db.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
                with db.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout = '3000ms'")
                    cur.execute(sql, params)
                    rows = cur.fetchall()
            if len(rows) > 1:
                raise ValueError('ambiguous authoritative record')
            return rows[0] if rows else None
        except Exception:
            raise PostgresAccessUnavailable('서버 기록을 조회하지 못했습니다') from None


class PostgresFindSessions(_ReadOnlyPostgres):
    def lookup(self, token_hash):
        if not isinstance(token_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', token_hash):
            return None
        row = self._query(SQL_FIND_SESSION, (token_hash,))
        if row is None:
            return None
        try:
            subject, session_id, expires, verified, consented, revoked, permissions = row
            if not isinstance(permissions, (list, tuple)) or not all(type(p) is str for p in permissions):
                raise ValueError('invalid permissions')
            return FindSession(Owner(subject, session_id), expires, verified, consented, revoked,
                               frozenset(permissions))
        except Exception:
            raise PostgresAccessUnavailable('인증 기록을 확인하지 못했습니다') from None


class PostgresOperationResults(_ReadOnlyPostgres):
    def __init__(self, dsn, binding_key, connect=None):
        super().__init__(dsn, connect)
        binding_digest(binding_key, 'validate-key', None)
        self._key = binding_key

    def get(self, owner, operation_id):
        scope = owner_scope(self._key, owner)
        if not isinstance(operation_id, str) or not re.fullmatch(r'op_[0-9a-f]{32}', operation_id):
            raise OperationNotFound('operation unavailable')
        row = self._query(SQL_OPERATION_RECEIPT, (operation_id, scope))
        if row is None:
            raise OperationNotFound('operation unavailable')
        try:
            op_id, row_scope, kind, fingerprint, state, result = row
            if isinstance(result, str):
                result = json.loads(result)
            operation = Operation(op_id, row_scope, kind, fingerprint, state, result)
            if op_id != operation_id or row_scope != scope or kind not in ('found', 'lost', 'answer', 'cancel_claim'):
                raise ValueError('unrelated operation')
            if state not in STATES or not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
                raise ValueError('invalid operation')
            if state == 'prepared':
                if result != {}:
                    raise ValueError('prepared result')
            else:
                OperationJournal._validate_receipt(operation, operation)
            return operation
        except Exception:
            raise PostgresAccessUnavailable('작업 기록을 확인하지 못했습니다') from None


def find_access_from_env(env=None):
    """시작 시 명시한 설정만 사용한다. .env 파일은 열지 않으며 미설정 시 기존 인증 잠금을 유지한다."""
    if env is None:
        import os
        env = os.environ
    session_dsn = env.get('LF_CHAT_SESSION_DATABASE_URL', '')
    operation_dsn = env.get('LF_CHAT_OPERATION_DATABASE_URL', '')
    key_hex = env.get('LF_CHAT_BINDING_KEY_HEX', '')
    if not any((session_dsn, operation_dsn, key_hex)):
        return None, None
    if not session_dsn or not re.fullmatch(r'[0-9a-fA-F]{64,128}', key_hex) or len(key_hex) % 2:
        raise ValueError('챗봇 인증 DB와 고정 결합 키 설정을 확인하세요')
    key = bytes.fromhex(key_hex)
    auth = FindSessionAuth(PostgresFindSessions(session_dsn).lookup, key)
    results = PostgresOperationResults(operation_dsn, key) if operation_dsn else None
    return auth, results
