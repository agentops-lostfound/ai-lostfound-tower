"""LF-5 영속 작업 계약 시제품. 명시적으로 주입하는 로컬 저장소이며 운영 연결은 없다.

desk는 작업 영수증과 업무 효과를 같은 트랜잭션에 저장해야 한다. 기존
SimDirector를 이 계약으로 감싸는 것만으로는 중복 방지를 보장할 수 없다.
Owner는 인증 어댑터가 제공하며 브라우저 session_id/가린 신분 값으로 만들지 않는다.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
from typing import Protocol
import uuid


KINDS = frozenset(('found', 'lost', 'answer', 'cancel_claim'))
TERMINAL = frozenset(('completed', 'rejected'))
STATES = frozenset(('prepared', 'running', 'uncertain', *TERMINAL))
RESULT_KEYS = frozenset(('item_id', 'claim_id', 'wait_id', 'pending_id'))


class OperationNotFound(LookupError):
    """없는 작업과 다른 소유자의 작업을 구분하지 않는다."""


class OperationConflict(ValueError):
    """같은 확인/작업 ID에 다른 업무 내용을 보내면 실행하지 않는다."""


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError('invalid operation identity')
    return value


@dataclass(frozen=True)
class Owner:
    subject: str
    auth_session: str

    def __post_init__(self):
        _text(self.subject)
        _text(self.auth_session)


@dataclass(frozen=True)
class Operation:
    operation_id: str
    owner_scope: str
    kind: str
    request_hash: str
    state: str
    result: dict


class OperationDesk(Protocol):
    """서버 내부 계약. lookup은 업무 효과/새 작업을 절대로 만들지 않는다."""

    def execute(self, operation: Operation, payload: dict) -> Operation: ...

    def lookup(self, operation: Operation) -> Operation | None: ...


@contextmanager
def connection(path):
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


class OperationJournal:
    """저장 전 ID 발급 → 한 번 전달 → 정확한 영수증만 조회해 복구.

    자체 업무 중복 제거는 desk 책임이다. 예외 후에는 재전달하지 않는다.
    기존 HTTP/위젯/IntakeAgent는 이 시제품을 사용하지 않는다.
    """

    def __init__(self, path: str | Path, binding_key: bytes):
        if not isinstance(binding_key, bytes) or len(binding_key) < 32:
            raise ValueError('a persistent binding key of at least 32 bytes is required')
        if str(path) == ':memory:':
            raise ValueError('a dedicated persistent journal path is required')
        self.path, self._key = Path(path), binding_key
        with connection(self.path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS chat_operations (
                operation_id TEXT PRIMARY KEY,
                owner_scope TEXT NOT NULL,
                confirmation_hash TEXT NOT NULL,
                kind TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                    ('prepared','running','uncertain','completed','rejected')),
                result TEXT NOT NULL DEFAULT '{}',
                UNIQUE(owner_scope, confirmation_hash)
            )''')

    def _digest(self, domain, value):
        encoded = json.dumps([domain, value], ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        return hmac.new(self._key, encoded, hashlib.sha256).hexdigest()

    def _owner(self, owner):
        if not isinstance(owner, Owner):
            raise ValueError('a server authenticated Owner is required')
        return self._digest('owner', [owner.subject, owner.auth_session])

    def _request(self, kind, payload):
        if kind not in KINDS or not isinstance(payload, dict):
            raise ValueError('invalid operation request')
        return self._digest('request', [kind, payload])

    @staticmethod
    def _row(row):
        return Operation(row['operation_id'], row['owner_scope'], row['kind'],
                         row['request_hash'], row['state'], json.loads(row['result']))

    def _load(self, db, scope, operation_id):
        if not isinstance(operation_id, str) or not re.fullmatch(r'op_[0-9a-f]{32}', operation_id):
            raise OperationNotFound('operation unavailable')
        row = db.execute('SELECT * FROM chat_operations WHERE operation_id=? AND owner_scope=?',
                         (operation_id, scope)).fetchone()
        if row is None:
            raise OperationNotFound('operation unavailable')
        return self._row(row)

    def get(self, owner: Owner, operation_id: str) -> Operation:
        with connection(self.path) as db:
            return self._load(db, self._owner(owner), operation_id)

    def prepare(self, owner: Owner, confirmation_id: str, kind: str, payload: dict) -> Operation:
        """확인 검사가 수락한 서버 초안 ID를 재사용한다. 원문/확인 토큰은 저장하지 않는다."""
        scope = self._owner(owner)
        proof = self._digest('confirmation', _text(confirmation_id))
        fingerprint = self._request(kind, payload)
        with connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row = db.execute('SELECT * FROM chat_operations WHERE owner_scope=? AND confirmation_hash=?',
                                 (scope, proof)).fetchone()
                if row is not None:
                    operation = self._row(row)
                    if operation.kind != kind or operation.request_hash != fingerprint:
                        raise OperationConflict('confirmation content changed')
                else:
                    operation_id = 'op_' + uuid.uuid4().hex
                    db.execute('INSERT INTO chat_operations '
                               '(operation_id,owner_scope,confirmation_hash,kind,request_hash,state) '
                               'VALUES (?,?,?,?,?,?)',
                               (operation_id, scope, proof, kind, fingerprint, 'prepared'))
                    operation = self._load(db, scope, operation_id)
                db.commit()
                return operation
            except BaseException:
                db.rollback()
                raise

    @staticmethod
    def _validate_receipt(original, receipt):
        if not isinstance(receipt, Operation):
            raise ValueError('invalid operation receipt')
        for key in ('operation_id', 'owner_scope', 'kind', 'request_hash'):
            if getattr(receipt, key) != getattr(original, key):
                raise ValueError('unrelated operation receipt')
        if receipt.state not in STATES - {'prepared'} or not isinstance(receipt.result, dict):
            raise ValueError('invalid operation receipt state')
        if receipt.state != 'completed':
            if receipt.result:
                raise ValueError('non-completed receipt cannot contain success identifiers')
            return
        if set(receipt.result) - RESULT_KEYS:
            raise ValueError('unsupported result field')
        for value in receipt.result.values():
            if not isinstance(value, str) or not value.strip() or len(value) > 120:
                raise ValueError('invalid result identifier')
        keys = set(receipt.result)
        valid = (('item_id' in keys) if original.kind == 'found' else
                 ({'item_id', 'claim_id'} <= keys) if original.kind == 'cancel_claim' else
                 bool(keys & {'claim_id', 'wait_id', 'pending_id'}))
        if not valid:
            raise ValueError('missing result identifier')

    def _save(self, original, receipt=None):
        state, result = ('uncertain', {}) if receipt is None else (receipt.state, receipt.result)
        with connection(self.path) as db:
            # 늦은 예외/조회가 다른 작업자의 확정 결과를 지우지 않는다.
            db.execute("UPDATE chat_operations SET state=?,result=? WHERE operation_id=? "
                       "AND owner_scope=? AND state IN ('running','uncertain')",
                       (state, json.dumps(result, sort_keys=True), original.operation_id, original.owner_scope))
            return self._load(db, original.owner_scope, original.operation_id)

    def dispatch(self, owner: Owner, operation_id: str, payload: dict, desk: OperationDesk) -> Operation:
        # 호출자가 같은 dict를 수정해도 검증한 내용과 전달 내용이 바뀌지 않게 복사한다.
        payload = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        operation = self.get(owner, operation_id)
        if operation.request_hash != self._request(operation.kind, payload):
            raise OperationConflict('operation content changed')
        if operation.state in TERMINAL:
            return operation
        with connection(self.path) as db:
            won = db.execute("UPDATE chat_operations SET state='running' WHERE operation_id=? "
                             "AND owner_scope=? AND state='prepared'",
                             (operation_id, operation.owner_scope)).rowcount
        if not won:
            return self.recover(owner, operation_id, desk)
        operation = self.get(owner, operation_id)
        try:
            receipt = desk.execute(operation, payload)
            self._validate_receipt(operation, receipt)
        except Exception:
            return self._save(operation)
        return self._save(operation, receipt)

    def recover(self, owner: Owner, operation_id: str, desk: OperationDesk) -> Operation:
        """원래 작업만 조회. 찾지 못해도 재저장/자동 해제하지 않는다."""
        operation = self.get(owner, operation_id)
        if operation.state in TERMINAL or operation.state == 'prepared':
            return operation
        try:
            receipt = desk.lookup(operation)
            self._validate_receipt(operation, receipt)
        except Exception:
            return self._save(operation)
        return self._save(operation, receipt)
