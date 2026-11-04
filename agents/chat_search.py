"""Read-only, parameterized candidate lookup. Demo data never represents real finds."""
import sqlite3
from contextlib import closing
from pathlib import Path
from agents.contracts import CATEGORIES, COLORS
from agents.lost_input import text_features

SEARCH_STATUSES = ('등록기계 보관', '본센터 보관')
SQL_SEARCH = """SELECT item_id, category, features->>'color', status
FROM item WHERE category = %s AND (%s::text IS NULL OR features->>'color' = %s)
AND status = ANY(%s) ORDER BY item_id LIMIT 3"""


def public_candidates(rows):
    # Explicit allowlist, including values. Never return arbitrary DB strings or secrets.
    result = []
    import re
    for iid, category, color, status in rows:
        if (not isinstance(iid, str) or not re.fullmatch(r'(?:DEMO-[0-9]{3}|[A-Z]-(?:[0-9]{8}-[0-9]{4}|W[0-9]{2}))', iid)
                or category not in CATEGORIES or color not in [*COLORS, None]
                or status not in SEARCH_STATUSES):
            continue
        result.append({'item_id': iid, 'category': category, 'color': color, 'status': status})
    return result[:3]


class DemoItemDatabase:
    mode = 'demo_sqlite'

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS chat_demo_item '
                       '(item_id TEXT PRIMARY KEY, category TEXT, color TEXT, status TEXT)')
            db.executemany('INSERT OR IGNORE INTO chat_demo_item VALUES (?, ?, ?, ?)', [
                ('DEMO-001', '지갑', '검정', '본센터 보관'),
                ('DEMO-002', '모형폰', '검정', '본센터 보관'),
                ('DEMO-003', 'USB', '회색', '등록기계 보관'),
                ('DEMO-004', '립밤', '흰색', '본센터 보관'),
                ('DEMO-005', '보조배터리', '흰색', '본센터 보관'),
                ('DEMO-006', '핸드크림', '흰색', '등록기계 보관')])

    def search(self, category, color):
        # Read-only connection: search cannot change fixtures or any user data.
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            rows = db.execute('SELECT item_id, category, color, status FROM chat_demo_item '
                              'WHERE category = ? AND (? IS NULL OR color = ?) '
                              'AND status IN (?, ?) ORDER BY item_id LIMIT 3',
                              (category, color, color, *SEARCH_STATUSES)).fetchall()
        return public_candidates(rows)


class PostgresItemSearch:
    mode = 'postgres'

    def __init__(self, dsn, connect=None):
        self._dsn, self._connect = dsn, connect

    def __repr__(self):
        return 'PostgresItemSearch(dsn=***)'

    def search(self, category, color):
        import psycopg
        connect = self._connect or psycopg.connect
        with connect(self._dsn, connect_timeout=5) as db:
            db.read_only = True
            with db.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '3000ms'")
                cur.execute(SQL_SEARCH, (category, color, color, list(SEARCH_STATUSES)))
                return public_candidates(cur.fetchall())


class SearchAgent:
    def __init__(self, database=None, authorize=None):
        self.database, self.authorize = database, authorize

    @property
    def mode(self):
        return self.database.mode if self.database else 'unconfigured'

    def ask(self, question, access_token=None):
        base = {'sources': [], 'candidates': [], 'item_search_performed': False,
                'database_mode': self.mode, 'reservation_created': False,
                'method': 'parameterized_read_only_item_search', 'scope': '물건 검색'}
        def response(status, answer, **extra):
            return {**base, 'status': status, 'answer': answer, **extra}
        if self.database is None:
            return response('search_unavailable', '물건 검색 DB가 연결되지 않았어요. 왼쪽에서 물건 설명을 먼저 정리할 수 있어요.')
        if self.mode != 'demo_sqlite':
            # Only a server-owned verifier can grant access. Client booleans are ignored.
            try:
                allowed = self.authorize is not None and self.authorize(access_token) is True
            except Exception:
                allowed = False
            if not allowed:
                return response('authentication_required', '실제 물건 조회에는 기존 찾기 절차의 본인인증·필수 동의 연결이 필요해요. 현재 채팅에서는 인증을 대신하지 않습니다.')
        desc, warnings = text_features(question)
        if desc['category'] not in CATEGORIES or warnings:
            return response('search_needs_details', '찾는 물건 한 종류와 색상을 알려주세요. 예: 검정 지갑 찾아줘. 지갑·휴대폰·USB·립밤·보조배터리·핸드크림을 구분할 수 있어요.')
        try:
            candidates = self.database.search(desc['category'], desc.get('color'))
        except Exception:
            return response('search_unavailable', '물건 DB를 조회하지 못했어요. 잠시 후 다시 시도해주세요.')
        demo = self.mode == 'demo_sqlite'
        prefix = '시연용 가상 DB 조회 결과입니다. 실제 습득물이 아닙니다.\n\n' if demo else ''
        answer = (f'조건에 맞는 후보 {len(candidates)}개를 찾았어요. 본인 물건으로 확정된 결과는 아닙니다.'
                  if candidates else '이번 조회 조건에 맞는 후보가 없어요. 색상이나 물건 종류를 확인해주세요. 전체 분실물의 존재 여부를 확정한 것은 아닙니다.')
        answer += '\n품목·색상 기준의 조회이며 날짜·역·키링 등의 다른 조건은 아직 반영하지 않았습니다.'
        return response('items_found' if candidates else 'items_not_found', prefix + answer,
                        candidates=candidates, item_search_performed=True,
                        search_filter={k: desc[k] for k in ('category', 'color') if k in desc},
                        scope='시연용 가상 물건 DB' if demo else '인증된 읽기 전용 후보 조회')
