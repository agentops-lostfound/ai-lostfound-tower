"""세션 발급·철회 트랜잭션을 검증하는 임시 SQLite 대역. 운영 연결 없음."""
import json

from agents.chat_find_auth import FindSession
from agents.chat_operations import Owner, connection


class SQLiteSessionStore:
    def __init__(self, path, after_commit=None):
        self.path, self.after_commit = path, after_commit
        with connection(path) as db:
            db.execute('''CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, proof_hash TEXT UNIQUE NOT NULL,
                subject_id TEXT NOT NULL, auth_session_id TEXT UNIQUE NOT NULL,
                issued_at REAL, expires_at REAL, verified_at REAL, consented_at REAL,
                policy_version TEXT, permissions TEXT, revoked_at REAL)''')

    def create(self, record, *, validate_before_write):
        with connection(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                validate_before_write()
                result = db.execute('''INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,NULL)
                    ON CONFLICT(proof_hash) DO NOTHING''',
                    (record.token_hash, record.proof_hash, record.owner.subject, record.owner.auth_session,
                     record.issued_at, record.expires_at, record.verified_at, record.consented_at,
                     record.policy_version, json.dumps(sorted(record.permissions))))
                inserted = result.rowcount == 1
                db.commit()
            except BaseException:
                db.rollback()
                raise
        if self.after_commit:
            self.after_commit()
        return inserted

    def lookup(self, token_hash):
        with connection(self.path) as db:
            row = db.execute('SELECT * FROM sessions WHERE token_hash=?', (token_hash,)).fetchone()
        if row is None:
            return None
        return FindSession(Owner(row['subject_id'], row['auth_session_id']), row['expires_at'],
                           row['verified_at'] is not None, row['consented_at'] is not None,
                           row['revoked_at'] is not None, frozenset(json.loads(row['permissions'])))

    def revoke(self, owner, now):
        with connection(self.path) as db:
            return db.execute('UPDATE sessions SET revoked_at=? WHERE subject_id=? AND auth_session_id=? '
                              'AND revoked_at IS NULL', (now, owner.subject, owner.auth_session)).rowcount == 1

    def revoke_subject(self, subject_id, now):
        with connection(self.path) as db:
            return db.execute('UPDATE sessions SET revoked_at=? WHERE subject_id=? AND revoked_at IS NULL',
                              (now, subject_id)).rowcount

    def count(self):
        with connection(self.path) as db:
            return db.execute('SELECT count(*) FROM sessions').fetchone()[0]
