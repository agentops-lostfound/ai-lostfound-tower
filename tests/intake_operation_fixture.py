"""팀 DB/로봇과 연결하지 않는 트랜잭션 창구 대역. 시험용 파일 DB만 사용한다."""
from dataclasses import replace
import json
import uuid

from agents.chat_operations import Operation, OperationNotFound, OperationConflict, connection


class SQLiteDesk:
    def __init__(self, path, *, after_commit=None, before_commit=None):
        self.path = path
        self.after_commit = after_commit
        self.before_commit = before_commit
        self.execute_calls = self.lookup_calls = 0
        with connection(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS receipts (
                operation_id TEXT PRIMARY KEY, owner_scope TEXT NOT NULL,
                kind TEXT NOT NULL, request_hash TEXT NOT NULL,
                state TEXT NOT NULL, result TEXT NOT NULL
            )''')
            db.execute('''CREATE TABLE IF NOT EXISTS business_effects (
                operation_id TEXT PRIMARY KEY REFERENCES receipts(operation_id),
                kind TEXT NOT NULL, result TEXT NOT NULL
            )''')

    @staticmethod
    def _read(db, operation):
        row = db.execute('SELECT * FROM receipts WHERE operation_id=?',
                         (operation.operation_id,)).fetchone()
        if row is None:
            return None
        if row['owner_scope'] != operation.owner_scope:
            raise OperationNotFound('operation unavailable')
        if row['kind'] != operation.kind or row['request_hash'] != operation.request_hash:
            raise OperationConflict('operation content changed')
        return Operation(row['operation_id'], row['owner_scope'], row['kind'],
                         row['request_hash'], row['state'], json.loads(row['result']))

    def lookup(self, operation):
        self.lookup_calls += 1
        with connection(self.path) as db:
            return self._read(db, operation)

    def execute(self, operation, payload):
        self.execute_calls += 1
        with connection(self.path) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            try:
                receipt = self._read(db, operation)
                if receipt is None:
                    if payload.get('reject'):
                        receipt = replace(operation, state='rejected', result={})
                    else:
                        suffix = uuid.uuid4().hex
                        if operation.kind == 'found':
                            result = {'item_id': 'I-' + suffix}
                        elif operation.kind == 'lost' and payload.get('waiting'):
                            result = {'wait_id': 'L-' + suffix}
                        elif operation.kind == 'lost' and payload.get('quiz'):
                            result = {'pending_id': 'P-' + suffix}
                        else:
                            result = {'claim_id': 'C-' + suffix, 'item_id': 'I-' + suffix}
                        receipt = replace(operation, state='completed', result=result)
                    db.execute('INSERT INTO receipts VALUES (?,?,?,?,?,?)',
                               (receipt.operation_id, receipt.owner_scope, receipt.kind,
                                receipt.request_hash, receipt.state, json.dumps(receipt.result)))
                    if receipt.state == 'completed':
                        db.execute('INSERT INTO business_effects VALUES (?,?,?)',
                                   (receipt.operation_id, receipt.kind, json.dumps(receipt.result)))
                    if self.before_commit:
                        self.before_commit()
                db.commit()
            except BaseException:
                db.rollback()
                raise
        if self.after_commit:
            self.after_commit()
        return receipt

    def effects(self):
        with connection(self.path) as db:
            return db.execute('SELECT count(*) FROM business_effects').fetchone()[0]
