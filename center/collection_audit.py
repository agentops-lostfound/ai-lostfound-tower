"""Read-only collection ledger audit. Findings never authorize physical actions."""
from agents.contracts import ITEM_ID_RE, ITEM_STATUS

SCOPE = '회수 원장 기록의 일관성 점검 · 실물 수량·인계 성공 확인 아님'
AFTER_ARRIVAL = [s for s in ITEM_STATUS if s not in ('등록기계 보관', '회수 중')]

# Only fixed SQL and public operational fields. No identity/contact/features.
BASE = """WITH members AS (
 SELECT ci.collection_id,ci.item_id,ci.arrived,i.item_id AS existing_item,
        c.collection_id AS existing_collection,i.machine_id AS item_machine,
        c.machine_id AS collection_machine,i.status,c.picked_at,c.request_id
 FROM public.collection_item ci
 LEFT JOIN public.collection c USING(collection_id)
 LEFT JOIN public.item i USING(item_id)
), batches AS (
 SELECT c.collection_id,c.machine_id,c.picked_at,c.arrived_at,c.request_id,
        count(ci.item_id) AS member_count,
        count(ci.item_id) FILTER(WHERE ci.arrived) AS arrived_count,
        EXISTS(SELECT 1 FROM public.collection_alert a WHERE a.collection_id=c.collection_id) AS has_alert
 FROM public.collection c LEFT JOIN public.collection_item ci USING(collection_id)
 GROUP BY c.collection_id,c.machine_id,c.picked_at,c.arrived_at,c.request_id
), membership AS (
 SELECT item_id,count(*) AS total,count(*) FILTER(WHERE NOT arrived) AS open_count,
        min(collection_id) AS collection_id
 FROM public.collection_item GROUP BY item_id
)"""

RULES = {
 'orphan_member': ('error', '회수 항목의 물건 또는 회수 묶음이 없습니다.',
     'SELECT item_id,collection_id FROM members WHERE existing_item IS NULL OR existing_collection IS NULL'),
 'machine_mismatch': ('error', '물건과 회수 묶음의 등록기계가 다릅니다.',
     'SELECT item_id,collection_id FROM members WHERE item_machine<>collection_machine'),
 'pending_status_mismatch': ('error', '도착 전 회수 항목의 물건 상태가 회수 중이 아닙니다.',
     "SELECT item_id,collection_id FROM members WHERE NOT arrived AND status<>'회수 중'"),
 'arrived_status_mismatch': ('error', '도착 체크된 물건이 도착 전 상태로 남아 있습니다.',
     'SELECT item_id,collection_id FROM members WHERE arrived AND NOT(status=ANY(%(after_arrival)s))'),
 'empty_collection': ('error', '회수 묶음에 물건이 없습니다.',
     'SELECT NULL::text AS item_id,collection_id FROM batches WHERE member_count=0'),
 'completion_mismatch': ('error', '전체 도착 체크와 회수 완료 시각이 맞지 않습니다.',
     'SELECT NULL::text AS item_id,collection_id FROM batches WHERE member_count>0 AND ((arrived_at IS NOT NULL)<>(member_count=arrived_count))'),
 'completion_before_pickup': ('error', '회수 완료 시각이 회수 시작 시각보다 빠릅니다.',
     'SELECT NULL::text AS item_id,collection_id FROM batches WHERE arrived_at<picked_at'),
 'multiple_open_collections': ('error', '같은 물건이 여러 도착 전 회수 항목에 걸려 있습니다.',
     'SELECT item_id,collection_id FROM membership WHERE open_count>1'),
 'multiple_collection_history': ('review', '여러 회수 묶음에 기록된 물건입니다. 재회수·과거 이력을 확인하세요.',
     'SELECT item_id,collection_id FROM membership WHERE total>1'),
 'transit_without_open_collection': ('review', '회수 중 물건에 도착 전 회수 원장이 없습니다. 시연·외부 경로 여부를 확인하세요.',
     "SELECT i.item_id,NULL::integer AS collection_id FROM public.item i WHERE i.status='회수 중' AND NOT EXISTS(SELECT 1 FROM public.collection_item ci WHERE ci.item_id=i.item_id AND NOT ci.arrived)"),
 'invalid_active_alert': ('error', '이미 도착했거나 회수 항목이 없는 물건의 미도착 알림이 남아 있습니다.',
     'SELECT a.item_id,a.collection_id FROM public.collection_alert a LEFT JOIN members m ON m.collection_id=a.collection_id AND m.item_id=a.item_id WHERE a.resolved_at IS NULL AND (m.item_id IS NULL OR m.arrived)'),
 'missing_active_alert': ('error', '도착 검토·알림 이력이 있는 묶음의 미도착 알림이 빠져 있습니다.',
     'SELECT m.item_id,m.collection_id FROM members m JOIN batches b USING(collection_id) WHERE NOT m.arrived AND (b.arrived_count>0 OR b.has_alert) AND NOT EXISTS(SELECT 1 FROM public.collection_alert a WHERE a.collection_id=m.collection_id AND a.item_id=m.item_id AND a.resolved_at IS NULL)'),
 'missing_pickup_history': ('error', 'LF-9 단일 회수 기록에 대응하는 회수 시작 상태 이력이 없습니다.',
     "SELECT m.item_id,m.collection_id FROM members m JOIN membership n USING(item_id) WHERE m.request_id IS NOT NULL AND n.total=1 AND NOT EXISTS(SELECT 1 FROM public.item_status_log l WHERE l.item_id=m.item_id AND l.from_status='등록기계 보관' AND l.to_status='회수 중' AND l.at>=m.picked_at)"),
 'missing_arrival_history': ('error', 'LF-9 단일 회수 기록에 대응하는 도착 상태 이력이 없습니다.',
     "SELECT m.item_id,m.collection_id FROM members m JOIN membership n USING(item_id) WHERE m.request_id IS NOT NULL AND n.total=1 AND m.arrived AND NOT EXISTS(SELECT 1 FROM public.item_status_log l WHERE l.item_id=m.item_id AND l.from_status='회수 중' AND l.to_status='본센터 보관' AND l.at>=m.picked_at)"),
}
ISSUES = BASE + ', issues AS (' + ' UNION ALL '.join(
    f"SELECT '{code}'::text AS code,'{severity}'::text AS severity,item_id,collection_id FROM ({sql}) finding"
    for code, (severity, _message, sql) in RULES.items()) + ') '


def unavailable(reason='database_unavailable'):
    return {'status': 'unavailable', 'completed': False, 'issue_count': None,
            'error_count': None, 'review_count': None, 'issues': [], 'summary': [],
            'truncated': False, 'counts': {}, 'scope': SCOPE, 'reason': reason}


def audit_collections(connect, sample_limit=50):
    if type(sample_limit) is not int or not 1 <= sample_limit <= 200:
        raise ValueError('표시 건수는 1~200 사이의 정수여야 합니다')
    if connect is None:
        return unavailable('database_not_configured')
    params = {'after_arrival': AFTER_ARRIVAL, 'sample_limit': sample_limit}
    try:
        with connect() as conn, conn.cursor() as cur:
            if getattr(conn, 'autocommit', False) is True:
                raise ValueError('A transaction is required for a consistent audit snapshot')
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cur.execute("SET LOCAL statement_timeout = '3s'")
            cur.execute(BASE + """ SELECT transaction_timestamp(),
              (SELECT count(*) FROM public.collection),
              (SELECT count(*) FROM public.collection_item),
              (SELECT count(*) FROM public.item WHERE status='회수 중'),
              (SELECT count(*) FROM public.collection_alert WHERE resolved_at IS NULL),
              (SELECT count(*) FROM batches WHERE member_count>0 AND arrived_count=0 AND NOT has_alert AND arrived_at IS NULL),
              (SELECT count(*) FROM members m JOIN membership n USING(item_id) WHERE m.request_id IS NULL OR n.total>1)
            """)
            checked_at, *counts = cur.fetchone()
            cur.execute(ISSUES + 'SELECT code,severity,count(*) FROM issues GROUP BY code,severity ORDER BY code', params)
            summary = [{'code': c, 'severity': s, 'count': int(n), 'message': RULES[c][1]} for c, s, n in cur.fetchall()]
            cur.execute(ISSUES + "SELECT code,severity,item_id,collection_id FROM issues ORDER BY CASE severity WHEN 'error' THEN 0 ELSE 1 END,code,collection_id NULLS LAST,item_id NULLS LAST LIMIT %(sample_limit)s", params)
            samples = cur.fetchall()
        issues = []
        for code, severity, iid, cid in samples:
            row = {'code': code, 'severity': severity, 'message': RULES[code][1]}
            if isinstance(iid, str) and ITEM_ID_RE.fullmatch(iid):
                row['item_id'] = iid
            if type(cid) is int and 1 <= cid <= 2_147_483_647:
                row['collection_id'] = cid
            issues.append(row)
        errors = sum(r['count'] for r in summary if r['severity'] == 'error')
        reviews = sum(r['count'] for r in summary if r['severity'] == 'review')
        return {'status': 'attention' if errors + reviews else 'ok', 'completed': True,
                'checked_at': checked_at.isoformat(), 'issue_count': errors + reviews,
                'error_count': errors, 'review_count': reviews, 'summary': summary,
                'issues': issues, 'sample_limit': sample_limit, 'truncated': errors + reviews > len(issues),
                'counts': dict(zip(('collections', 'members', 'transit_items', 'active_alerts',
                                   'unreviewed_collections', 'history_members_unchecked'), map(int, counts))),
                'scope': SCOPE,
                'limitations': ['마감시각·도착 검토 시각이 없어 검토 전 묶음의 알림 누락은 판정하지 않습니다.',
                                '과거·복수 회수의 상태 이력 귀속과 중복 여부는 확정하지 않습니다.',
                                '점검 항목 수는 누락 물건 수가 아닙니다. 기록을 자동 수정하지 않습니다.']}
    except Exception:
        # Incomplete/timeout/schema/permission failures must not look like zero issues.
        return unavailable()
