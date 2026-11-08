"""LF-9: limited Korean Text2SQL; SQL is generated from a closed template."""
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, date, time, timedelta, timezone

from agents.contracts import category_label

KST = timezone(timedelta(hours=9))
CATEGORIES = {"지갑": "지갑", "usb": "USB", "립밤": "립밤", "휴대폰": "모형폰",
              "휴대전화": "모형폰", "핸드폰": "모형폰", "유에스비": "USB", "모형폰": "모형폰", "핸드크림": "핸드크림", "보조배터리": "보조배터리"}


@dataclass(frozen=True)
class CountQuery:
    sql: str
    params: tuple
    day: date
    machine_id: str | None
    category: str | None


def plan_count(question, now=None):
    if not isinstance(question, str) or not 1 <= len(question) <= 300:
        raise ValueError("통계 질문은 1~300자로 입력하세요")
    q = unicodedata.normalize('NFKC', question).lower().strip()
    if re.search(r"[;'\"`]|--|/\*|\b(select|drop|delete|insert|update|union|pg_|claim|contact)\b|이름|전화번호|신분|동의|개인정보", q):
        raise ValueError("물건 접수 건수만 질문할 수 있습니다")
    if not re.search(r"몇\s*개|몇\s*건|개수|건수", q) or not re.search(r"들어온|접수|등록", q):
        raise ValueError("예: 오늘 등록기계 A에 들어온 USB 몇 개?")
    # Reject clauses whose meaning cannot be represented by this single-count template.
    if re.search(r"회수|반환|수령|센터|이상|이하|제외|빼고|각각|별로|최근|이번|동안|부터|까지", q):
        raise ValueError("현재는 하루의 접수 건수만 지원합니다")
    instant = now or datetime.now(KST)
    if instant.tzinfo is None:
        raise ValueError("현재 시각에 시간대가 필요합니다")
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", q)
    relative = [v for v in ("오늘", "어제") if v in q]
    if len(dates) + len(relative) != 1:
        raise ValueError("오늘·어제 또는 YYYY-MM-DD 중 하루를 지정하세요")
    day = date.fromisoformat(dates[0]) if dates else instant.astimezone(KST).date() - timedelta(days=1 if relative == ["어제"] else 0)
    if day > instant.astimezone(KST).date():
        raise ValueError('미래 날짜의 접수 통계는 조회할 수 없습니다')
    if re.search(r"검정|검은|빨강|파랑|갈색|흰색|색상|스티커|흠집|가죽", q):
        raise ValueError("색상·특징 조건은 아직 통계 질문에서 지원하지 않습니다")
    machines = set(re.findall(r"(?:등록기계\s*|kiosk-)([a-z])(?=\s|에|의|$)", q))
    if len(machines) > 1:
        raise ValueError("등록기계 하나씩 질문하세요")
    machine = "KIOSK-" + next(iter(machines)).upper() if machines else None
    if re.search(r"등록기계|kiosk", q) and not machine and "전체" not in q:
        raise ValueError("등록기계 A처럼 기계 번호를 지정하세요")
    cats = {v for k, v in CATEGORIES.items() if k in re.sub(r'\s+', '', q)}
    if len(cats) > 1:
        raise ValueError("품목 하나씩 질문하세요")
    category = next(iter(cats), None)
    if category is None and not re.search(r"전체|모든|물건|분실물", q):
        raise ValueError("품목을 확인하거나 전체 물건이라고 입력하세요")
    # Refuse unrepresented conditions instead of silently dropping station/color/brand filters.
    rest = re.sub(r'\s+', '', q)
    rest = re.sub(r'\d{4}-\d{2}-\d{2}|오늘|어제', '', rest)
    rest = re.sub(r'(?:등록기계|kiosk-)[a-z](?:에서|에|의)?|전체등록기계(?:에서|에|의)?', '', rest)
    rest = re.sub('|'.join(sorted(map(re.escape, CATEGORIES), key=len, reverse=True)), '', rest)
    rest = re.sub(r'들어온|접수된|접수|등록된|등록|전체|모든|분실물|물건|몇개|몇건|개수|건수|인가요|인가|알려주세요|알려줘|입니까|야|는|은|을|를|이|가|[?？.!]', '', rest)
    if rest:
        raise ValueError('하루·등록기계·품목별 접수 건수만 지원합니다. 예: 오늘 등록기계 A에 들어온 USB 몇 개?')
    start = datetime.combine(day, time.min, KST)
    clauses = ["received_at >= %s", "received_at < %s"]
    params = [start, start + timedelta(days=1)]
    for key, val in (("machine_id", machine), ("category", category)):
        if val:
            clauses.append(key + " = %s")
            params.append(val)
    return CountQuery("SELECT count(*) FROM public.stats_item WHERE " + " AND ".join(clauses), tuple(params), day, machine, category)


class Statistics:
    def __init__(self, connect):
        self.connect = connect

    def ask(self, question, now=None):
        query = plan_count(question, now)
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL ROLE lf_stats_reader")
            cur.execute("SET LOCAL statement_timeout = '3s'")
            cur.execute(query.sql, query.params)
            count = int(cur.fetchone()[0])
        return count_response(query, count, query.sql, query.params, 'public.stats_item', 'postgres')


def count_response(query, count, sql, parameters, source, mode):
    return {'answer': f"{query.day} {query.machine_id or '전체 등록기계'} {category_label(query.category) if query.category else '전체 물건'} 접수는 {count}건입니다.",
            'count': count, 'sql': sql,
            'parameters': [v.isoformat() if isinstance(v, datetime) else v for v in parameters],
            'source': source, 'database_mode': mode, 'supported_scope': '하루·등록기계·품목별 접수 건수',
            'filters': {'day': query.day.isoformat(), 'machine_id': query.machine_id, 'category': query.category,
                        'timezone': 'Asia/Seoul', 'start_inclusive': query.params[0].isoformat(),
                        'end_exclusive': query.params[1].isoformat()}}
