"""PostgreSQL 연결 대역 + 실제 임시 SQLite 거래/참조 제약/동적 조회 뷰.

네이티브 PostgreSQL 시험이 아니다. 고정 SQL의 파라미터/순서를 해석해 SQLite에 전달한다.
"""
from datetime import datetime, timezone
from contextlib import closing
import json
import sqlite3

from agents.chat_identity_evidence import (
    SQL_IDENTITY, SQL_CONSENT, SQL_STORE_PROOF, SQL_READ_PROOF, SQL_LOCK_PROOF,
    SQL_CURRENT_POLICY, SQL_STORE_CONSENT, SQL_REVOKE_PROOF, SQL_REVOKE_CONSENT,
)
from agents.chat_postgres_access import SQL_FIND_SESSION
from agents.chat_session_issuer import SQL_CREATE_SESSION, SQL_REVOKE_SESSION, SQL_REVOKE_SUBJECT, SQL_LOCK_SUBJECT


class EvidenceDatabase:
    def __init__(self, path):
        self.path, self.calls, self.hook = path, [], None
        with closing(sqlite3.connect(path)) as db, db:
            db.executescript('''
CREATE TABLE providers(provider TEXT PRIMARY KEY, active INTEGER NOT NULL);
INSERT INTO providers VALUES ('trusted-test-provider',1);
CREATE TABLE policy(purpose TEXT PRIMARY KEY,version TEXT);
INSERT INTO policy VALUES ('lostfound.find','policy-v1');
CREATE TABLE proofs(proof_hash TEXT PRIMARY KEY,ref_hash TEXT UNIQUE,subject TEXT,proof_id TEXT,
 verified REAL,expires REAL,purpose TEXT,provider TEXT REFERENCES providers,assurance TEXT,revoked REAL,
 UNIQUE(proof_hash,subject));
CREATE TABLE consents(ref_hash TEXT PRIMARY KEY,subject TEXT,version TEXT,consented REAL,accepted INTEGER,revoked REAL,
 UNIQUE(subject,version,consented));
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,proof_hash TEXT UNIQUE,subject TEXT,session_id TEXT UNIQUE,
 issued REAL,expires REAL,verified REAL,consented REAL,version TEXT,permissions TEXT,revoked REAL,
 FOREIGN KEY(proof_hash,subject) REFERENCES proofs(proof_hash,subject),
 FOREIGN KEY(subject,version,consented) REFERENCES consents(subject,version,consented));
CREATE VIEW proof_access AS SELECT p.* FROM proofs p JOIN providers t ON t.provider=p.provider AND t.active;
CREATE VIEW consent_access AS SELECT c.* FROM consents c JOIN policy p ON p.version=c.version;
CREATE VIEW session_access AS SELECT s.* FROM sessions s
 JOIN proofs p ON p.proof_hash=s.proof_hash AND p.subject=s.subject AND p.verified=s.verified
 JOIN providers t ON t.provider=p.provider AND t.active
 JOIN consents c ON c.subject=s.subject AND c.version=s.version AND c.consented=s.consented
 JOIN policy ps ON ps.version=c.version
 WHERE p.assurance='verified' AND p.revoked IS NULL AND c.accepted AND c.revoked IS NULL;
''')

    def connect(self, *_args, **_kwargs):
        return _Connection(self)

    def change(self, sql, params=()):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(sql, params)

    def count(self, table):
        if table not in ('proofs', 'consents', 'sessions'):
            raise ValueError('test table')
        with closing(sqlite3.connect(self.path)) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]


class _Connection:
    def __init__(self, server):
        self.server, self.db = server, sqlite3.connect(server.path, timeout=10, isolation_level=None)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.autocommit, self.read_only, self.isolation_level = True, False, None
        self.started = False
    def __enter__(self): return self
    def __exit__(self, exc, *_):
        try:
            self.db.rollback() if exc else self.db.commit()
        finally:
            self.db.close()
        return False
    def cursor(self): return _Cursor(self)


class _Cursor:
    def __init__(self, connection):
        self.c, self.rows = connection, []
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def fetchone(self): return self.rows.pop(0) if self.rows else None
    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows
    def execute(self, sql, params=None):
        c = self.c
        c.server.calls.append((sql, params, c.read_only, c.autocommit))
        if c.server.hook:
            c.server.hook(sql)
        if sql == "SET LOCAL statement_timeout = '3000ms'":
            if c.autocommit:
                raise AssertionError('autocommit must be disabled')
            c.db.execute('PRAGMA query_only=' + ('ON' if c.read_only else 'OFF'))
            c.db.execute('BEGIN' if c.read_only else 'BEGIN IMMEDIATE')
            c.started = True
            self.rows = []
            return
        if not c.started:
            raise AssertionError('transaction was not started')
        if sql == SQL_LOCK_SUBJECT:
            self.rows = []
            return  # SQLite의 BEGIN IMMEDIATE가 대역의 쓰기를 직렬화
        values = [v.timestamp() if isinstance(v, datetime) else v for v in (params or ())]
        if sql == SQL_IDENTITY:
            rows = c.db.execute('SELECT subject,proof_id,verified,expires,purpose,provider,assurance,revoked IS NOT NULL '
                                'FROM proof_access WHERE ref_hash=?', values).fetchall()
            self.rows = [(*r[:-1], bool(r[-1])) for r in rows]
        elif sql == SQL_CONSENT:
            rows = c.db.execute('SELECT subject,version,consented,accepted,revoked IS NOT NULL '
                                'FROM consent_access WHERE ref_hash=? AND subject=?', values).fetchall()
            self.rows = [(*r[:3], bool(r[3]), bool(r[4])) for r in rows]
        elif sql == SQL_FIND_SESSION:
            rows = c.db.execute('SELECT subject,session_id,expires,verified IS NOT NULL,consented IS NOT NULL,'
                                'revoked IS NOT NULL,permissions FROM session_access WHERE token_hash=?', values).fetchall()
            self.rows = [(r[0],r[1],r[2],bool(r[3]),bool(r[4]),bool(r[5]),json.loads(r[6])) for r in rows]
        elif sql in (SQL_READ_PROOF, SQL_LOCK_PROOF):
            rows = c.db.execute('SELECT subject,proof_id,verified,expires,purpose,provider,assurance,revoked '
                                'FROM proofs WHERE ref_hash=?', values).fetchall()
            self.rows = [(r[0],r[1],datetime.fromtimestamp(r[2],timezone.utc),
                          datetime.fromtimestamp(r[3],timezone.utc),*r[4:]) for r in rows]
        elif sql == SQL_CURRENT_POLICY:
            self.rows = c.db.execute("SELECT version FROM policy WHERE purpose='lostfound.find'").fetchall()
        elif sql == SQL_STORE_PROOF:
            self.rows = c.db.execute('INSERT INTO proofs VALUES (?,?,?,?,?,?,?,?,?,NULL) '
                'ON CONFLICT(proof_hash) DO NOTHING RETURNING proof_id', values).fetchall()
        elif sql == SQL_STORE_CONSENT:
            self.rows = c.db.execute('INSERT INTO consents VALUES (?,?,?,?,?,NULL) RETURNING ref_hash', values).fetchall()
        elif sql == SQL_CREATE_SESSION:
            values[-1] = json.dumps(values[-1])
            self.rows = c.db.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,NULL) '
                'ON CONFLICT(proof_hash) DO NOTHING RETURNING session_id', values).fetchall()
        elif sql == SQL_REVOKE_SESSION:
            self.rows = c.db.execute('UPDATE sessions SET revoked=? WHERE subject=? AND session_id=? '
                'AND revoked IS NULL RETURNING session_id', values).fetchall()
        elif sql == SQL_REVOKE_SUBJECT:
            self.rows = c.db.execute('UPDATE sessions SET revoked=? WHERE subject=? AND revoked IS NULL '
                'RETURNING session_id', values).fetchall()
        elif sql in (SQL_REVOKE_PROOF, SQL_REVOKE_CONSENT):
            table, field = ('proofs','proof_id') if sql == SQL_REVOKE_PROOF else ('consents','ref_hash')
            self.rows = c.db.execute('UPDATE ' + table + ' SET revoked=? WHERE ref_hash=? AND subject=? '
                'AND revoked IS NULL RETURNING ' + field, values).fetchall()
        else:
            raise AssertionError('unknown production SQL')
