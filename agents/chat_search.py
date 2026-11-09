"""Read-only, parameterized candidate lookup. Demo data never represents real finds."""
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from datetime import datetime, time, timedelta
from agents.contracts import CATEGORIES, COLORS, category_label
from agents.lost_input import KST
from agents.search_context import search_context
from agents.candidate_registry import CandidateRegistry

SEARCH_STATUSES = ('등록기계 보관', '본센터 보관')
DEMO_MODES = ('demo_sqlite', 'sim_tower')          # 가짜 물건만 다루는 검색 — 본인인증 없이 후보 조회 가능
MACHINE_STATIONS = {'KIOSK-A': '해운대', 'KIOSK-C': '서면', 'CENTER': '부산'}
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
                ('DEMO-002', '모형폰', '검정', '본센터 보관', '1호선', '서면', recent),
                ('DEMO-003', 'USB', '회색', '등록기계 보관', '1호선', '서면', recent),
                ('DEMO-004', '립밤', '흰색', '본센터 보관', '2호선', '해운대', recent),
                ('DEMO-005', '보조배터리', '흰색', '본센터 보관', '2호선', '해운대', recent),
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


class SimTowerItemSearch:
    """11/7 가상 시연(TOWER_SIM=1): 관제탑이 들고 있는 가상 물건 목록을 그대로 찾는다.
    한줄 설명: 챗봇이 연습용 별도 목록이 아니라 화면 작업대에 보이는 물건과 같은 목록을 보게 한다.
    - list_items() → 가상 세계 물건 기록 목록(item_id·category·features.color·status·machine_id·received_at)
    - 읽기만 한다. 역을 말했는데 그 역 물건이 없으면 역 조건 없이 다시 찾는다(시연 물건은 본센터 직접 접수라서)"""
    mode = 'sim_tower'

    def __init__(self, list_items):
        self._list = list_items

    def search(self, category, color, context=None):
        context = context or {}
        since = context.get('lost_date')

        def select(station):
            out = []
            for r in self._list() or []:
                feats = r.get('features') or {}
                if r.get('category') != category or r.get('status') not in SEARCH_STATUSES:
                    continue
                if color and feats.get('color') != color:
                    continue
                if station and MACHINE_STATIONS.get(r.get('machine_id')) != station:
                    continue
                if since and str(r.get('received_at') or '')[:10] < since:
                    continue
                out.append(r)
            out.sort(key=lambda r: (str(r.get('received_at') or ''), r.get('item_id')), reverse=True)
            return [(r.get('item_id'), r.get('category'), (r.get('features') or {}).get('color'), r.get('status')) for r in out]
        rows = select(context.get('lost_station'))
        if not rows and context.get('lost_station'):
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
        if self.mode not in DEMO_MODES and not self._authorized(access_token):
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
        if self.mode not in DEMO_MODES:
            # Only a server-owned verifier can grant access. Client booleans are ignored.
            if not self._authorized(access_token):
                return response('authentication_required', '실제 물건 조회에는 기존 찾기 절차의 본인인증·필수 동의 연결이 필요해요. 현재 채팅에서는 인증을 대신하지 않습니다.')
        desc, warnings = search_context(question, context)
        if any(w.startswith('색상') for w in warnings):   # 11/6: 여러 색이면 무엇이 문제인지 정확히 되묻는다
            return response('search_needs_details', '색이 두 가지 이상으로 보여요. 물건에서 가장 넓게 보이는 색 하나로 다시 알려주세요. '
                            '예: 검정 지갑 찾아줘. 무늬·키링 같은 특징은 후보를 찾은 뒤 확인 질문에서 비교해요.')
        if desc['category'] not in CATEGORIES or desc['category'] == '없음' or warnings:
            return response('search_needs_details', '찾는 물건 한 종류와 색상을 알려주세요. 예: 검정 지갑 찾아줘. 지갑·휴대폰·USB·립밤·보조배터리·핸드크림을 구분할 수 있어요.')
        if self.mode not in DEMO_MODES and not all(desc.get(k) for k in ('lost_date', 'lost_line', 'lost_station')):
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
        demo = self.mode in DEMO_MODES
        # 11/9 실제 모델 시험: 답마다 고지 문구 3줄이 붙어 길었다 → 핵심(찾음/없음)을 먼저, 고지는 끝에 한 줄
        suffix = ('\n(가상 시연 관제탑 목록 — 실제 습득물이 아닙니다)' if self.mode == 'sim_tower'
                  else '\n(시연용 가상 DB — 실제 습득물이 아닙니다)' if demo else '')
        answer = (f'후보 {len(candidates)}개를 찾았어요. 본인 물건으로 확정된 건 아니에요.'
                  if candidates else '조건에 맞는 후보가 없어요. 색이나 물건 종류를 바꿔 보세요. 분실물이 없다고 확정한 것은 아닙니다.')
        applied = [category_label(desc['category'])]
        if desc.get('color') == '기타':
            applied.append('목록 밖 색(보라·주황 등)')
        elif desc.get('color'):
            applied.append(desc['color'])
        else:
            applied.append('모든 색')
        if desc.get('lost_date'):
            applied.append('분실 날짜 이후 접수')
        if desc.get('lost_station') and self.mode == 'sim_tower':
            applied.append('입력한 역 우선, 없으면 모든 역')
        elif desc.get('lost_station') and desc.get('lost_line'):
            applied.append('입력한 역 우선, 없으면 같은 호선')
        elif desc.get('lost_station'):
            applied.append('입력한 역')
        elif desc.get('lost_line'):
            applied.append('입력한 호선')
        answer += '\n찾은 조건: ' + ' · '.join(applied)
        if re.search(r'키링|열쇠고리|스티커|흠집|긁힌|케이스|고리|이니셜|무늬|그림|로고', question or ''):
            answer += '\n키링 같은 추가 특징은 아직 검색에 반영하지 않았어요.'
        if candidates and self.mode == 'sim_tower':
            answer += ("\n\n내 물건 같다면 '잃어버린 물건 찾기' 화면에서 분실 신고를 해 주세요. 확인 질문에 답하면 찾기 번호가 나오고, "
                       "부산역 본센터 키오스크에서 그 번호와 신분 확인으로 물건을 받을 수 있어요.")
        return response('items_found' if candidates else 'items_not_found', answer + suffix,
                        candidates=[{'candidate_no': i, 'category': c['category'], 'color': c['color']} for i, c in enumerate(candidates, 1)],
                        search_result_id=reference, item_search_performed=True,
                        search_filter=desc,
                        scope=('가상 시연 관제탑 물건' if self.mode == 'sim_tower' else '시연용 가상 물건 DB') if demo
                        else '인증된 읽기 전용 후보 조회')
