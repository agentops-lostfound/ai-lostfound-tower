"""Read-only synthetic record consistency checks; never proves physical inventory."""
from collections import Counter
from datetime import datetime, timezone
from agents.contracts import ITEM_ID_RE


def audit_demo(store):
    with store.connection() as db:
        items = {r['item_id']: dict(r) for r in db.execute('SELECT item_id,machine_id,status FROM demo_item')}
        batches = {r['collection_id']: dict(r) for r in db.execute('SELECT collection_id,machine_id,arrived_at,arrival_reviewed_at FROM demo_collection')}
        members = [dict(r) for r in db.execute('SELECT collection_id,item_id,arrived FROM demo_member')]
        events = Counter((r[0], r[1], r[2]) for r in db.execute('SELECT collection_id,item_id,status FROM demo_event'))
        alerts = {(r[0], r[1]) for r in db.execute('SELECT collection_id,item_id FROM demo_alert WHERE resolved_at IS NULL')}
        revision = store._check_revision(db, None)
    issues = []
    def issue(code, text, iid=None, cid=None):
        row = {'code': code, 'message': text}
        if isinstance(iid, str) and ITEM_ID_RE.fullmatch(iid):
            row['item_id'] = iid
        if type(cid) is int and 1 <= cid <= 2_147_483_647:
            row['collection_id'] = cid
        issues.append(row)
    membership = Counter(m['item_id'] for m in members)
    pairs = {(m['collection_id'], m['item_id']): m for m in members}
    expected_events = Counter()
    for member in members:
        cid, iid = member['collection_id'], member['item_id']
        item, batch = items.get(iid), batches.get(cid)
        if not item or not batch:
            issue('orphan_member', '회수 항목의 물건 또는 회수 묶음이 없습니다.', iid, cid)
            continue
        if item['machine_id'] != batch['machine_id']:
            issue('machine_mismatch', '물건과 회수 묶음의 등록기계가 다릅니다.', iid, cid)
        expected_status = '본센터 보관' if member['arrived'] else '회수 중'
        if item['status'] != expected_status:
            issue('status_mismatch', '도착 체크와 물건 상태가 다릅니다.', iid, cid)
        expected_events[(cid, iid, '회수 중')] = 1
        if member['arrived']:
            expected_events[(cid, iid, '본센터 보관')] = 1
    for iid, item in items.items():
        expected = 0 if item['status'] == '등록기계 보관' else 1
        if item['status'] not in ('등록기계 보관', '회수 중', '본센터 보관') or membership[iid] != expected:
            issue('membership_mismatch', '물건 상태에 맞는 회수 기록 수가 아닙니다.', iid)
    for key in set(events) | set(expected_events):
        if events[key] != expected_events[key]:
            issue('history_mismatch', '회수·도착 상태 이력이 누락되거나 중복되었습니다.', key[1], key[0])
    for cid, batch in batches.items():
        group = [m for m in members if m['collection_id'] == cid]
        complete = bool(group) and all(m['arrived'] for m in group)
        if not group or bool(batch['arrived_at']) != complete:
            issue('completion_mismatch', '전체 도착 체크와 회수 완료 시각이 맞지 않습니다.', cid=cid)
        # Before any arrival review, in-transit items need not have alerts yet.
        reviewed = bool(batch['arrival_reviewed_at']) or any(m['arrived'] for m in group) or any(c == cid for c, _ in alerts)
        if reviewed:
            for member in group:
                if not member['arrived'] and (cid, member['item_id']) not in alerts:
                    issue('missing_alert', '도착 확인에서 빠진 물건의 미도착 알림이 없습니다.', member['item_id'], cid)
    for cid, iid in alerts:
        member = pairs.get((cid, iid))
        if not member or member['arrived']:
            issue('invalid_alert', '이미 도착했거나 회수에 속하지 않은 물건의 알림이 남아 있습니다.', iid, cid)
    return {'mode': 'demo_sqlite', 'revision': revision, 'status': 'ok' if not issues else 'attention',
            'checked_at': datetime.now(timezone.utc).isoformat(), 'issue_count': len(issues), 'issues': issues[:50],
            'truncated': len(issues) > 50, 'counts': {'items': len(items), 'collections': len(batches), 'events': sum(events.values())},
            'scope': '가상 DB의 기록 일관성 점검 · 실물 누락 여부 확인 아님'}
