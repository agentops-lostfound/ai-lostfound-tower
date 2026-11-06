"""Read-only, parameterized candidate lookup. Demo data never represents real finds."""
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, time, timedelta
from agents.contracts import CATEGORIES, COLORS
from agents.lost_input import KST
from agents.search_context import search_context
from agents.candidate_registry import CandidateRegistry

SEARCH_STATUSES = ('등록기계 보관', '본센터 보관')
SQL_SEARCH = """SELECT i.item_id, i.category, i.features->>'color', i.status
FROM item i JOIN machine m ON m.machine_id = i.machine_id
WHERE i.category = %s AND (%s::text IS NULL OR i.features->>'color' = %s)
AND i.status = ANY(%s) AND (%s::text IS NULL OR m.line = %s)
AND (%s::text IS NULL OR regexp_replace(m.station, '역$', '') = %s)
AND (%s::timestamptz IS NULL OR i.received_at >= %s)
AND i.received_at <= now() ORDER BY i.received_at DESC, i.item_id LIMIT 3"""


def received_since(context):
    return datetime.combine(datetime.fromisoformat(context['lost_date']).date(), time.min, KST) if context.get('lost_date') else None


def public_candidates(rows):
    # Adapter-internal projection. Item IDs must be replaced by ordinal cards at the API boundary.
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

    def __init__(self, path, today=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS chat_demo_catalog '
                       '(item_id TEXT PRIMARY KEY, category TEXT, color TEXT, status TEXT, line TEXT, station TEXT, received_date TEXT)')
            day = today or datetime.now(KST).date()
            recent, older = day.isoformat(), (day - timedelta(days=3)).isoformat()
            # Fixed synthetic IDs. Refresh synthetic reception dates when a new demo starts.
            db.executemany('INSERT INTO chat_demo_catalog VALUES (?, ?, ?, ?, ?, ?, ?) '
                           'ON CONFLICT(item_id) DO UPDATE SET received_date=excluded.received_date', [
                ('DEMO-001', '지갑', '검정', '본센터 보관', '2호선', '해운대', recent),
                ('DEMO-002', '모형폰', '검정', '본센터 보관', '1호선', '중앙', recent),
                ('DEMO-003', 'USB', '회색', '등록기계 보관', '1호선', '서면', recent),
                ('DEMO-004', '립밤', '흰색', '본센터 보관', '2호선', '해운대', recent),
                ('DEMO-005', '보조배터리', '흰색', '본센터 보관', '1호선', '중앙', recent),
                ('DEMO-006', '핸드크림', '흰색', '등록기계 보관', '1호선', '서면', older)])

    def search(self, category, color, context=None):
        context = context or {}
        # Read-only connection: search cannot change fixtures or any user data.
        with closing(sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            def select(station):
                return db.execute('SELECT item_id, category, color, status FROM chat_demo_catalog '
                              'WHERE category = ? AND (? IS NULL OR color = ?) '
                              'AND status IN (?, ?) AND (? IS NULL OR line = ?) '
                              'AND (? IS NULL OR station = ?) AND (? IS NULL OR received_date >= ?) '
                              'ORDER BY received_date DESC, item_id LIMIT 3',
                              (category, color, color, *SEARCH_STATUSES, context.get('lost_line'), context.get('lost_line'),
                               station, station, context.get('lost_date'), context.get('lost_date'))).fetchall()
            rows = select(context.get('lost_station'))
            if not rows and context.get('lost_station') and context.get('lost_line'):
                rows = select(None)
        return public_candidates(rows)


class PostgresItemSearch:
    mode = 'postgres'

    def __init__(self, dsn, connect=None):
        self._dsn, self._connect = dsn, connect

    def __repr__(self):
        return 'PostgresItemSearch(dsn=***)'

    def search(self, category, color, context=None):
        context = context or {}
        import psycopg
        connect = self._connect or psycopg.connect
        with connect(self._dsn, connect_timeout=5) as db:
            db.read_only = True
            db.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            with db.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout = '3000ms'")
                def select(station):
                    since = received_since(context)
                    cur.execute(SQL_SEARCH, (category, color, color, list(SEARCH_STATUSES),
                        context.get('lost_line'), context.get('lost_line'), station, station, since, since))
                    return cur.fetchall()
                rows = select(context.get('lost_station'))
                if not rows and context.get('lost_station') and context.get('lost_line'):
                    rows = select(None)
                return public_candidates(rows)


class SearchAgent:
    def __init__(self, database=None, authorize=None, registry=None):
        self.database, self.authorize = database, authorize
        self.registry = registry or CandidateRegistry()

    def _authorized(self, token):
        if not isinstance(token, str) or not 1 <= len(token) <= 4096 or self.authorize is None:
            return False
        try:
            return self.authorize(token) is True
        except Exception:
            return False

    def resolve_candidate(self, reference, candidate_no, access_token):
        """Trusted LF-6 server integration only; there is deliberately no public ID-reveal route."""
        if self.mode != 'demo_sqlite' and not self._authorized(access_token):
            raise ValueError('인증·필수 동의 확인이 필요합니다')
        return self.registry.resolve(reference, candidate_no, access_token)

    @property
    def mode(self):
        return self.database.mode if self.database else 'unconfigured'

    def ask(self, question, access_token=None, context=None):
        base = {'sources': [], 'candidates': [], 'item_search_performed': False,
                'database_mode': self.mode, 'reservation_created': False,
                'method': 'parameterized_read_only_item_search', 'scope': '물건 검색'}
        def response(status, answer, **extra):
            return {**base, 'status': status, 'answer': answer, **extra}
        if self.database is None:
            return response('search_unavailable', '물건 검색 DB가 연결되지 않았어요. 왼쪽에서 물건 설명을 먼저 정리할 수 있어요.')
        if self.mode != 'demo_sqlite':
            # Only a server-owned verifier can grant access. Client booleans are ignored.
            if not self._authorized(access_token):
                return response('authentication_required', '실제 물건 조회에는 기존 찾기 절차의 본인인증·필수 동의 연결이 필요해요. 현재 채팅에서는 인증을 대신하지 않습니다.')
        desc, warnings = search_context(question, context)
        if desc['category'] not in CATEGORIES or desc['category'] == '없음' or warnings:
            return response('search_needs_details', '찾는 물건 한 종류와 색상을 알려주세요. 예: 검정 지갑 찾아줘. 지갑·모형폰(휴대폰)·USB·립밤·보조배터리·핸드크림을 구분할 수 있어요.')
        if self.mode != 'demo_sqlite' and not all(desc.get(k) for k in ('lost_date', 'lost_line', 'lost_station')):
            return response('search_needs_details', '실제 후보 검색에는 분실 날짜·호선·역이 필요해요. 왼쪽 설명을 확인하거나 질문에 함께 입력해주세요.')
        try:
            candidates = self.database.search(desc['category'], desc.get('color'), desc)
            # Defense at the final boundary also covers future custom database adapters.
            candidates = public_candidates([(c.get('item_id'), c.get('category'), c.get('color'), c.get('status')) for c in candidates[:3]])
            seen, unique = set(), []
            for candidate in candidates:
                if candidate['item_id'] not in seen:
                    seen.add(candidate['item_id'])
                    unique.append(candidate)
            candidates = unique
            reference = self.registry.issue([c['item_id'] for c in candidates], access_token) if candidates else None
        except Exception:
            return response('search_unavailable', '물건 DB를 조회하지 못했어요. 잠시 후 다시 시도해주세요.')
        demo = self.mode == 'demo_sqlite'
        prefix = '시연용 가상 DB 조회 결과입니다. 실제 습득물이 아닙니다.\n\n' if demo else ''
        answer = (f'조건에 맞는 후보 {len(candidates)}개를 찾았어요. 본인 물건으로 확정된 결과는 아닙니다.'
                  if candidates else '이번 조회 조건에 맞는 후보가 없어요. 색상이나 물건 종류를 확인해주세요. 전체 분실물의 존재 여부를 확정한 것은 아닙니다.')
        applied = ['품목']
        if desc.get('color'):
            applied.append('색상')
        if desc.get('lost_date'):
            applied.append('분실 날짜 이후 접수')
        if desc.get('lost_station') and desc.get('lost_line'):
            applied.append('입력한 역 우선, 없으면 같은 호선')
        elif desc.get('lost_station'):
            applied.append('입력한 역')
        elif desc.get('lost_line'):
            applied.append('입력한 호선')
        answer += '\n이번 조회 조건: ' + ' · '.join(applied) + '. 키링 등 추가 특징은 아직 검색에 반영하지 않았습니다.'
        return response('items_found' if candidates else 'items_not_found', prefix + answer,
                        candidates=[{'candidate_no': i, 'category': c['category'], 'color': c['color']} for i, c in enumerate(candidates, 1)],
                        search_result_id=reference, item_search_performed=True,
                        search_filter=desc,
                        scope='시연용 가상 물건 DB' if demo else '인증된 읽기 전용 후보 조회')
