"""팀 DB 에 쌓인 지난 가상 시연 물건 정리 — 발표 전 정리용 (LF-8, 11/10 변재원)

한줄 설명: 가상 시연(TOWER_SIM=1)이 팀 DB 에도 함께 저장한 **가상 물건**(item.object_id = 'SIM')과 거기에만 딸린 기록
(상태 기록·보관 칸·찾기 요청·확인 질문·방문 예약·반환 기록·반환 단계)을 한 번에 지운다. 되돌릴 수 없다.

왜: 관제탑을 켤 때마다 가상 시연의 처음 물건과 연습 기록이 팀 DB 에 쌓인다. 발표 때 DBeaver·[팀 DB 조회] 화면이 지난 연습 기록으로 붐비지 않게 치운다.

사용법 (저장소 폴더, .venv 켠 상태, 팀 DB 켜진 상태)
    python tools/purge_sim_items.py                      # 미리보기: 오늘 이전 날짜의 가상 물건 목록(아무것도 지우지 않음)
    python tools/purge_sim_items.py --apply              # 실제로 지움
    python tools/purge_sim_items.py --all                # 오늘 것까지(관제탑을 끈 뒤에만 — 켜 둔 관제탑의 처음 물건도 지워짐)
    python tools/purge_sim_items.py --before 20261111    # 이 날짜 이전 접수 번호만

- **진짜 기록은 건드리지 않는다**: 가상 표시('SIM')가 없는 물건(키오스크 사진 접수·직원 접수)은 지우지 않는다.
  찾기 요청이 진짜 물건에도 걸려 있으면 그 찾기 요청은 남긴다. 보관 칸은 이 부품이 쓴 칸(assigned_by='system')만 비운다
- 번호는 접수 번호의 날짜(A-YYYYMMDD-…)로 나눈다. 시연용 정답지 번호(A-W01 등)는 날짜가 없어 --all 일 때만 대상
- 한 번에(트랜잭션 하나로) 지운다 — 중간에 실패하면 아무것도 지워지지 않는다
- 이름·전화 같은 값은 찍지 않고 번호와 개수만 보여 준다. DATABASE_URL(비밀번호 포함)은 출력하지 않는다
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DAY = re.compile(r"^[A-Z]-([0-9]{8})-[0-9]{4}$")
# 가상 물건과 함께 지우는 표 — 순서가 중요하다(가리키는 쪽부터). 표 이름은 이 고정 목록뿐
CHILD_TABLES = ("quiz_attempt", "reservation", "claim_candidate", "inventory_check", "collection_item",
                "finder_contact", "item_status_log")


def pick(rows: list[str], before: str | None, include_all: bool) -> list[str]:
    """가상 물건 번호 중 지울 것: include_all 이면 전부, 아니면 접수 날짜가 before(YYYYMMDD) 보다 앞선 것만"""
    if include_all:
        return sorted(rows)
    out = []
    for iid in rows:
        m = DAY.match(iid)
        if m and before and m.group(1) < before:
            out.append(iid)
    return sorted(out)


def purge_sim(dsn: str, apply: bool = False, before: str | None = None, include_all: bool = False,
              connect: Callable | None = None) -> dict:
    """→ {"items": [지운(지울) 물건], "kept_today": n, "claims": n, "cases": n, "slots": n}"""
    if connect is None:
        import psycopg
        connect = lambda d: psycopg.connect(d, connect_timeout=5)  # noqa: E731
    before = before or date.today().strftime("%Y%m%d")
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT item_id FROM item WHERE object_id LIKE 'SIM%%'")
        sim = [r[0] for r in cur.fetchall()]
        ids = pick(sim, before, include_all)
        out = {"items": ids, "kept_today": len(sim) - len(ids), "claims": 0, "cases": 0, "slots": 0}
        if not ids:
            return out
        # 이 물건들에만 걸린 찾기 요청(진짜 물건에도 걸린 요청은 남긴다)
        cur.execute("SELECT claim_id FROM claim_candidate WHERE item_id = ANY(%s) UNION SELECT claim_id FROM quiz_attempt WHERE item_id = ANY(%s) "
                    "UNION SELECT claim_id FROM reservation WHERE item_id = ANY(%s) "
                    "UNION SELECT claim_id FROM return_case WHERE item_id = ANY(%s) AND claim_id IS NOT NULL", (ids,) * 4)
        claims = [r[0] for r in cur.fetchall()]
        cur.execute("SELECT count(*) FROM return_case WHERE item_id = ANY(%s)", (ids,))
        out["cases"] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM storage_assignment WHERE item_id = ANY(%s) AND assigned_by = 'system'", (ids,))
        out["slots"] = cur.fetchone()[0]
        if claims:
            cur.execute("SELECT count(DISTINCT c) FROM unnest(%s::text[]) c WHERE NOT EXISTS ("
                        "SELECT 1 FROM reservation r WHERE r.claim_id = c AND NOT (r.item_id = ANY(%s)) UNION ALL "
                        "SELECT 1 FROM quiz_attempt q WHERE q.claim_id = c AND NOT (q.item_id = ANY(%s)) UNION ALL "
                        "SELECT 1 FROM claim_candidate x WHERE x.claim_id = c AND NOT (x.item_id = ANY(%s)) UNION ALL "
                        "SELECT 1 FROM return_case y WHERE y.claim_id = c AND NOT (y.item_id = ANY(%s)))", (claims, ids, ids, ids, ids))
            out["claims"] = cur.fetchone()[0]
        if not apply:
            return out
        # 진짜 직원·관제탑이 넣은 칸이 가상 물건을 가리키면 지울 수 없다(외래 키) → 그 물건은 남긴다
        cur.execute("SELECT DISTINCT item_id FROM storage_assignment WHERE item_id = ANY(%s) AND assigned_by <> 'system'", (ids,))
        held = {r[0] for r in cur.fetchall()}
        if held:
            ids = [i for i in ids if i not in held]
            out["items"] = ids
            out["held_by_staff_slot"] = sorted(held)
            if not ids:
                return out
        cur.execute("DELETE FROM return_step WHERE case_id IN (SELECT case_id FROM return_case WHERE item_id = ANY(%s))", (ids,))
        cur.execute("DELETE FROM return_case WHERE item_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM storage_assignment WHERE item_id = ANY(%s) AND assigned_by = 'system'", (ids,))
        for table in CHILD_TABLES:
            cur.execute(f"DELETE FROM {table} WHERE item_id = ANY(%s)", (ids,))
        if claims:                     # 남은 연결이 하나도 없는 찾기 요청만
            cur.execute("DELETE FROM claim c WHERE c.claim_id = ANY(%s) "
                        "AND NOT EXISTS (SELECT 1 FROM claim_candidate x WHERE x.claim_id = c.claim_id) "
                        "AND NOT EXISTS (SELECT 1 FROM quiz_attempt x WHERE x.claim_id = c.claim_id) "
                        "AND NOT EXISTS (SELECT 1 FROM reservation x WHERE x.claim_id = c.claim_id) "
                        "AND NOT EXISTS (SELECT 1 FROM return_case x WHERE x.claim_id = c.claim_id)", (claims,))
        cur.execute("DELETE FROM item WHERE item_id = ANY(%s) AND object_id LIKE 'SIM%%'", (ids,))
    return out


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="팀 DB 의 지난 가상 시연 물건과 딸린 기록 지우기(되돌릴 수 없음)")
    ap.add_argument("--apply", action="store_true", help="실제로 지움(없으면 미리보기만)")
    ap.add_argument("--all", action="store_true", help="오늘 것까지 모두(관제탑을 끈 뒤에만)")
    ap.add_argument("--before", help="이 날짜(YYYYMMDD) 이전 접수 번호만(기본: 오늘)")
    a = ap.parse_args(argv)
    if a.before and not re.fullmatch(r"[0-9]{8}", a.before):
        print("[purge_sim_items] --before 는 YYYYMMDD(예: 20261111)")
        return 2
    from tools.envfile import load_env
    load_env()
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("[purge_sim_items] DATABASE_URL 이 비어 있습니다(.env 확인)")
        return 2
    try:
        r = purge_sim(dsn, apply=a.apply, before=a.before, include_all=a.all)
    except Exception as e:
        print(f"[purge_sim_items] 팀 DB 작업 실패({type(e).__name__}) — 아무것도 지우지 않았습니다. 팀 DB(Docker)가 켜져 있는지 확인하세요")
        return 1
    word = "지움" if a.apply else "지울 대상(미리보기 — 아직 지우지 않음)"
    print(f"[purge_sim_items] {word}: 가상 물건 {len(r['items'])}개 · 찾기 요청 {r['claims']}건 · 반환 기록 {r['cases']}건 · 보관 칸 {r['slots']}칸")
    if r["items"]:
        print("[purge_sim_items] 물건 번호: " + ", ".join(r["items"][:30]) + (f" 외 {len(r['items']) - 30}개" if len(r["items"]) > 30 else ""))
    if r.get("kept_today"):
        print(f"[purge_sim_items] 남김: 오늘(또는 --before 날짜 이후) 가상 물건 {r['kept_today']}개 — 모두 지우려면 관제탑을 끈 뒤 --all")
    if r.get("held_by_staff_slot"):
        print("[purge_sim_items] 직원·관제탑이 넣은 보관 칸에 걸려 남긴 물건: " + ", ".join(r["held_by_staff_slot"]))
    if not a.apply and r["items"]:
        print("[purge_sim_items] 실제로 지우려면 같은 명령 끝에 --apply 를 붙이세요(되돌릴 수 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
