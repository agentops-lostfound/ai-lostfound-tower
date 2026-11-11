"""잘못 들어간 접수(물건) 지우기 — 시연 정리용 (LF-8, 11/10 변재원)

한줄 설명: 번호를 준 물건을 팀 DB 에서 **완전히 지운다**(물건 행 + 상태 기록 + 습득자 연락처). 되돌릴 수 없다.
시연 연습 중에 사진 분석이 안 된 채 남은 접수(품목 '확인 불가')를 발표 전에 치우려고 만들었다.

사용법 (저장소 폴더, .venv 켠 상태, 팀 DB 켜진 상태)
    python tools/purge_items.py A-20261110-0001..0007            # 미리보기(아무것도 지우지 않음)
    python tools/purge_items.py A-20261110-0001..0007 --apply    # 실제로 지움
    python tools/purge_items.py A-20261110-0003 H-20261110-0006 --apply

- `번호..끝자리` 는 그 사이 번호를 모두 뜻한다(A-20261110-0001..0007 = 0001 ~ 0007)
- **다른 기록에 걸린 물건은 지우지 않는다**: 찾기 요청 후보·확인 질문·방문 예약·반환 기록·회수 묶음·보관 칸에 연결돼 있으면 건너뛰고 이유를 보여 준다
  (그런 물건을 지우면 반환·찾기 기록이 깨진다 — 필요하면 그 기록부터 사람이 판단)
- 사진 파일(data/photos/…)은 지우지 않는다(파일은 Git 에 안 올라가며, 필요하면 폴더에서 직접 정리)
- 이름·전화 같은 값은 화면에 찍지 않고 물건 번호와 개수만 보여 준다
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ITEM_ID = re.compile(r"^[A-Z]-([0-9]{8}-[0-9]{4}|W[0-9]{2})$")
RANGE = re.compile(r"^([A-Z]-[0-9]{8}-)([0-9]{4})\.\.([0-9]{4})$")
# 물건이 걸려 있으면 지우지 않는 표(표 이름, 쉬운 이름)
BLOCKERS = (("claim_candidate", "찾기 요청 후보"), ("quiz_attempt", "확인 질문 기록"), ("reservation", "방문 예약"),
            ("return_case", "반환 기록"), ("collection_item", "회수 묶음"), ("storage_assignment", "보관 칸"),
            ("inventory_check", "보관함 개수 확인"))
# 물건과 함께 지우는 표(물건에만 딸린 기록)
OWNED = ("finder_contact", "item_status_log")


def expand(args: list[str]) -> list[str]:
    """번호 목록 펴기: `A-20261110-0001..0007` → 0001 ~ 0007. 형식이 틀리면 ValueError"""
    out: list[str] = []
    for a in args:
        m = RANGE.match(a)
        if m:
            lo, hi = int(m.group(2)), int(m.group(3))
            if hi < lo or hi - lo > 500:
                raise ValueError(f"범위가 이상합니다: {a}")
            out += [f"{m.group(1)}{n:04d}" for n in range(lo, hi + 1)]
        elif ITEM_ID.match(a):
            out.append(a)
        else:
            raise ValueError(f"물건 번호 형식이 아닙니다: {a}")
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def purge_items(dsn: str, item_ids: list[str], apply: bool = False, connect: Callable | None = None) -> dict:
    """→ {"deleted": [지운(지울) 번호], "missing": [없는 번호], "blocked": {번호: [걸린 기록 이름]}}.
    한 번에(트랜잭션 하나로) 지운다 — 중간에 실패하면 아무것도 지워지지 않는다"""
    if connect is None:
        import psycopg
        connect = lambda d: psycopg.connect(d, connect_timeout=5)  # noqa: E731
    out = {"deleted": [], "missing": [], "blocked": {}}
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT item_id FROM item WHERE item_id = ANY(%s)", (item_ids,))
        have = {r[0] for r in cur.fetchall()}
        out["missing"] = [i for i in item_ids if i not in have]
        for table, easy in BLOCKERS:
            cur.execute(f"SELECT DISTINCT item_id FROM {table} WHERE item_id = ANY(%s)", (item_ids,))   # 표 이름은 위 고정 목록
            for (iid,) in cur.fetchall():
                out["blocked"].setdefault(iid, []).append(easy)
        ok = [i for i in item_ids if i in have and i not in out["blocked"]]
        out["deleted"] = ok
        if apply and ok:
            for table in OWNED:
                cur.execute(f"DELETE FROM {table} WHERE item_id = ANY(%s)", (ok,))
            cur.execute("DELETE FROM item WHERE item_id = ANY(%s)", (ok,))
    return out


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="번호를 준 물건을 팀 DB 에서 지우기(되돌릴 수 없음)")
    ap.add_argument("items", nargs="+", help="물건 번호 또는 범위(A-20261110-0001..0007)")
    ap.add_argument("--apply", action="store_true", help="실제로 지움(없으면 미리보기만)")
    a = ap.parse_args(argv)
    try:
        ids = expand(a.items)
    except ValueError as e:
        print(f"[purge_items] {e}")
        return 2
    from tools.envfile import load_env
    load_env()
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("[purge_items] DATABASE_URL 이 비어 있습니다(.env 확인)")
        return 2
    try:
        r = purge_items(dsn, ids, apply=a.apply)
    except Exception as e:
        print(f"[purge_items] 팀 DB 작업 실패({type(e).__name__}) — 아무것도 지우지 않았습니다. 팀 DB(Docker)가 켜져 있는지 확인하세요")
        return 1
    word = "지움" if a.apply else "지울 대상(미리보기 — 아직 지우지 않음)"
    print(f"[purge_items] {word} {len(r['deleted'])}건: {', '.join(r['deleted']) or '없음'}")
    if r["missing"]:
        print(f"[purge_items] 팀 DB 에 없는 번호 {len(r['missing'])}건: {', '.join(r['missing'])}")
    for iid, why in r["blocked"].items():
        print(f"[purge_items] 건너뜀 {iid} — 다른 기록에 연결됨: {', '.join(why)}")
    if not a.apply and r["deleted"]:
        print("[purge_items] 실제로 지우려면 같은 명령 끝에 --apply 를 붙이세요(되돌릴 수 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
