"""Synthetic, local SQLite collection desk. Never reads team DB environment variables."""
import re
import sqlite3
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from center.collections import CollectionError, item_ids
from agents.contracts import MACHINE_LETTERS


def now():
    return datetime.now(timezone.utc).isoformat()


class StaleDemo(CollectionError):
    code = 'stale_demo'


def collection_number(cid):
    if type(cid) is not int or not 1 <= cid <= 2_147_483_647:
        raise CollectionError('회수 번호를 확인해주세요')
    return cid


class DemoCollections:
    mode = 'demo_sqlite'

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(write=True) as db:
            schema = '''
                CREATE TABLE IF NOT EXISTS demo_metadata (version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS demo_item (
                    item_id TEXT PRIMARY KEY, machine_id TEXT, category TEXT, color TEXT, status TEXT);
                CREATE TABLE IF NOT EXISTS demo_collection (
                    collection_id INTEGER PRIMARY KEY AUTOINCREMENT, machine_id TEXT,
                    request_id TEXT UNIQUE, picked_at TEXT, arrived_at TEXT);
                CREATE TABLE IF NOT EXISTS demo_member (
                    collection_id INTEGER, item_id TEXT, arrived INTEGER DEFAULT 0,
                    PRIMARY KEY(collection_id,item_id));
                CREATE TABLE IF NOT EXISTS demo_alert (
                    collection_id INTEGER, item_id TEXT, created_at TEXT, resolved_at TEXT,
                    PRIMARY KEY(collection_id,item_id));
                CREATE TABLE IF NOT EXISTS demo_event (
                    id INTEGER PRIMARY KEY, collection_id INTEGER, item_id TEXT, status TEXT, at TEXT);
                CREATE TABLE IF NOT EXISTS demo_place (
                    place_id INTEGER PRIMARY KEY AUTOINCREMENT,line TEXT,station TEXT,label TEXT,
                    UNIQUE(line,station,label));
            '''
            # executescript implicitly commits; keep bootstrap and seeding in one write transaction.
            for statement in schema.split(';'):
                if statement.strip():
                    db.execute(statement)
            if 'revision' not in {r[1] for r in db.execute('PRAGMA table_info(demo_metadata)')}:
                db.execute('ALTER TABLE demo_metadata ADD COLUMN revision TEXT')
            if 'received_at' not in {r[1] for r in db.execute('PRAGMA table_info(demo_item)')}:
                db.execute('ALTER TABLE demo_item ADD COLUMN received_at INTEGER')
            if 'arrival_reviewed_at' not in {r[1] for r in db.execute('PRAGMA table_info(demo_collection)')}:
                db.execute('ALTER TABLE demo_collection ADD COLUMN arrival_reviewed_at TEXT')
            db.execute('UPDATE demo_item SET received_at=? WHERE received_at IS NULL',
                       (int(datetime.now(timezone.utc).timestamp() * 1_000_000),))
            db.execute('CREATE VIEW IF NOT EXISTS demo_stats_item AS SELECT received_at,machine_id,category FROM demo_item')
            if not db.execute('SELECT 1 FROM demo_metadata').fetchone():
                self._seed(db)
                db.execute('INSERT INTO demo_metadata(version,revision) VALUES(1,?)', (secrets.token_hex(16),))
            db.execute('UPDATE demo_metadata SET revision=? WHERE revision IS NULL', (secrets.token_hex(16),))
            if not db.execute('SELECT 1 FROM demo_place').fetchone():
                self._seed_places(db)
            # KIOSK-C uses S (Seomyeon), keeping C reserved for claim IDs.
            canonical = MACHINE_LETTERS['KIOSK-C'] + '-W01'
            legacy = db.execute("SELECT 1 FROM demo_item WHERE item_id='C-W01' AND machine_id='KIOSK-C'").fetchone()
            if legacy and canonical != 'C-W01':
                if db.execute('SELECT 1 FROM demo_item WHERE item_id=?', (canonical,)).fetchone():
                    raise CollectionError('서면 시연 물건 번호가 중복되었습니다. 기록 확인이 필요합니다')
                for table in ('demo_item', 'demo_member', 'demo_alert', 'demo_event'):
                    db.execute('UPDATE '+table+' SET item_id=? WHERE item_id=?', (canonical, 'C-W01'))
                db.execute('UPDATE demo_metadata SET revision=? WHERE version=1', (secrets.token_hex(16),))

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            else:
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _seed_places(db):
        db.executemany('INSERT INTO demo_place(line,station,label) VALUES(?,?,?)',
                       [(line, station, f'가상 장소 {i:02d}') for line, station in
                        [('2호선', '해운대'), ('1호선', '중앙'), ('1호선', '서면')] for i in range(1, 7)])

    @staticmethod
    def _seed(db):
        rows = [
            ('A-W01', 'KIOSK-A', '지갑', '검정', '등록기계 보관'),
            ('A-W02', 'KIOSK-A', 'USB', '회색', '등록기계 보관'),
            ('A-W03', 'KIOSK-A', '립밤', '흰색', '등록기계 보관'),
            ('B-W01', 'KIOSK-B', '모형폰', '검정', '등록기계 보관'),
            ('B-W02', 'KIOSK-B', '보조배터리', '흰색', '등록기계 보관'),
            (MACHINE_LETTERS['KIOSK-C']+'-W01', 'KIOSK-C', '핸드크림', '흰색', '등록기계 보관')]
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
        db.executemany('INSERT INTO demo_item(item_id,machine_id,category,color,status,received_at) VALUES(?,?,?,?,?,?)',
                       [(*row, timestamp) for row in rows])

    @staticmethod
    def _check_revision(db, revision):
        current = db.execute('SELECT revision FROM demo_metadata WHERE version=1').fetchone()[0]
        if revision is not None and (not isinstance(revision, str) or not re.fullmatch(r'[0-9a-f]{32}', revision)
                                     or not secrets.compare_digest(revision, current)):
            raise StaleDemo('시연 데이터가 초기화되었습니다. 새로고침 후 다시 선택해주세요')
        return current

    @staticmethod
    def _view(db, cid):
        collection_number(cid)
        row = db.execute('SELECT * FROM demo_collection WHERE collection_id=?', (cid,)).fetchone()
        if row is None:
            raise CollectionError('회수 기록이 없습니다')
        members = [dict(r) for r in db.execute('SELECT m.item_id,m.arrived,i.category,i.color '
            'FROM demo_member m JOIN demo_item i USING(item_id) WHERE collection_id=? ORDER BY item_id', (cid,))]
        for member in members:
            member['arrived'] = bool(member['arrived'])
        missing = [m['item_id'] for m in members if not m['arrived']]
        return {'collection_id': row['collection_id'], 'machine_id': row['machine_id'],
                'picked_at': row['picked_at'], 'arrived_at': row['arrived_at'], 'items': members,
                'missing_item_ids': missing, 'alert_status': 'preview' if db.execute(
                    'SELECT 1 FROM demo_alert WHERE collection_id=? AND resolved_at IS NULL', (cid,)).fetchone() else 'none'}

    def get(self, cid):
        with self.connection() as db:
            return self._view(db, cid)

    def pickup(self, machine_id, ids, request_id, *, revision=None):
        ids = item_ids(ids)
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', request_id):
            raise CollectionError('같은 회수 요청의 재시도에는 동일한 request_id가 필요합니다')
        if machine_id not in ('KIOSK-A', 'KIOSK-B', 'KIOSK-C'):
            raise CollectionError('등록기계를 확인해주세요')
        with self.connection(write=True) as db:
            self._check_revision(db, revision)
            old = db.execute('SELECT collection_id FROM demo_collection WHERE request_id=?', (request_id,)).fetchone()
            if old:
                view = self._view(db, old[0])
                if view['machine_id'] != machine_id or sorted(m['item_id'] for m in view['items']) != ids:
                    raise CollectionError('같은 요청 번호에 다른 회수 내용을 사용할 수 없습니다')
                return view
            rows = db.execute('SELECT item_id,machine_id,status FROM demo_item WHERE item_id IN (' + ','.join('?' for _ in ids) + ')', ids).fetchall()
            if len(rows) != len(ids) or any(r['machine_id'] != machine_id or r['status'] != '등록기계 보관' for r in rows):
                raise CollectionError('선택한 모든 물건이 해당 등록기계 보관 상태여야 합니다')
            timestamp = now()
            cid = db.execute('INSERT INTO demo_collection(machine_id,request_id,picked_at) VALUES(?,?,?)',
                             (machine_id, request_id, timestamp)).lastrowid
            for iid in ids:
                db.execute('INSERT INTO demo_member(collection_id,item_id) VALUES(?,?)', (cid, iid))
                db.execute("UPDATE demo_item SET status='회수 중' WHERE item_id=?", (iid,))
                db.execute('INSERT INTO demo_event(collection_id,item_id,status,at) VALUES(?,?,?,?)', (cid, iid, '회수 중', timestamp))
            return self._view(db, cid)

    def arrive(self, cid, ids, *, revision=None):
        ids = item_ids(ids, allow_empty=True)
        with self.connection(write=True) as db:
            self._check_revision(db, revision)
            view = self._view(db, cid)
            members = {m['item_id']: m['arrived'] for m in view['items']}
            if not set(ids) <= members.keys():
                raise CollectionError('해당 회수에 포함되지 않은 물건입니다')
            timestamp = now()
            for iid in ids:
                if members[iid]:
                    continue
                row = db.execute('SELECT status FROM demo_item WHERE item_id=?', (iid,)).fetchone()
                if row is None or row[0] != '회수 중':
                    raise CollectionError('물건 상태가 변경되었습니다. 다시 확인해주세요')
                db.execute('UPDATE demo_member SET arrived=1 WHERE collection_id=? AND item_id=?', (cid, iid))
                db.execute("UPDATE demo_item SET status='본센터 보관' WHERE item_id=?", (iid,))
                db.execute('INSERT INTO demo_event(collection_id,item_id,status,at) VALUES(?,?,?,?)', (cid, iid, '본센터 보관', timestamp))
                db.execute('UPDATE demo_alert SET resolved_at=? WHERE collection_id=? AND item_id=?', (timestamp, cid, iid))
                members[iid] = True
            db.execute('UPDATE demo_collection SET arrival_reviewed_at=? WHERE collection_id=?', (timestamp, cid))
            for iid, arrived in members.items():
                if not arrived:
                    db.execute('INSERT OR IGNORE INTO demo_alert(collection_id,item_id,created_at) VALUES(?,?,?)', (cid, iid, timestamp))
            if all(members.values()):
                db.execute('UPDATE demo_collection SET arrived_at=COALESCE(arrived_at,?) WHERE collection_id=?', (timestamp, cid))
            return self._view(db, cid)

    def dashboard(self):
        with self.connection() as db:
            items = [dict(r) for r in db.execute('SELECT * FROM demo_item ORDER BY machine_id,item_id')]
            collections = [self._view(db, r[0]) for r in db.execute('SELECT collection_id FROM demo_collection ORDER BY collection_id DESC LIMIT 100')]
            alerts = [dict(r) for r in db.execute('SELECT collection_id,item_id,created_at FROM demo_alert WHERE resolved_at IS NULL ORDER BY created_at')]
            return {'mode': self.mode, 'revision': self._check_revision(db, None), 'items': items, 'collections': collections, 'alerts': alerts,
                    'event_count': db.execute('SELECT count(*) FROM demo_event').fetchone()[0]}

    def reset(self, *, revision=None):
        with self.connection(write=True) as db:
            self._check_revision(db, revision)
            for table in ('demo_alert', 'demo_event', 'demo_member', 'demo_collection', 'demo_item', 'demo_place'):
                db.execute('DELETE FROM ' + table)
            self._seed(db)
            self._seed_places(db)
            db.execute('UPDATE demo_metadata SET revision=? WHERE version=1', (secrets.token_hex(16),))
        return {'reset': True, 'mode': self.mode}
