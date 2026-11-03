"""습득자 연락처 보관 기간 지키기 — LF-8 (docs/design/database.md 6장).

한줄 설명: 물건이 '인계 완료'된 지 30일이 지난 습득자 연락처(이름·전화)를 지운다. 개인정보를 필요한 기간만 갖고 있기 위한 도구.

사용법 (저장소 폴더, .venv 켠 상태, 팀 DB 켜진 상태)
    python tools/purge_contacts.py            # 지울 대상 개수만 보여 줌(아무것도 지우지 않음)
    python tools/purge_contacts.py --apply    # 실제로 지움(관제탑 켤 때 start_tower.bat 가 자동 실행)

- 기준: item_status_log 에서 그 물건이 마지막으로 '인계 완료'가 된 시각 + 30일(contracts.CONTACT_RETENTION_DAYS)
- 물건이 지금도 '인계 완료' 상태일 때만 지운다(반환 보류·되돌림 등으로 상태가 바뀌었으면 남김)
- 이름·전화는 화면에 찍지 않고 물건 번호와 개수만 보여 준다
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import CONTACT_RETENTION_DAYS  # noqa: E402

_TARGET = (
    "FROM finder_contact fc JOIN item i ON i.item_id = fc.item_id "
    "WHERE i.status = '인계 완료' AND ("
    "SELECT max(l.at) FROM item_status_log l WHERE l.item_id = i.item_id AND l.to_status = '인계 완료'"
    ") < now() - make_interval(days => %s)"
)
SQL_PREVIEW = "SELECT fc.item_id " + _TARGET + " ORDER BY fc.item_id"
SQL_DELETE = ("DELETE FROM finder_contact WHERE item_id IN (SELECT fc.item_id " + _TARGET + ") "
              "RETURNING item_id")


def purge_contacts(dsn: str, apply: bool = False, days: int = CONTACT_RETENTION_DAYS,
                   connect: Callable | None = None) -> list[str]:
    """지울(apply=True 면 지운) 물건 번호 목록."""
    if connect is None:
        import psycopg
        connect = lambda d: psycopg.connect(d, connect_timeout=5)  # noqa: E731
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(SQL_DELETE if apply else SQL_PREVIEW, (days,))
        return sorted(r[0] for r in cur.fetchall())


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="인계 완료 30일 지난 습득자 연락처 지우기")
    ap.add_argument("--apply", action="store_true", help="실제로 지움(없으면 미리보기만)")
    a = ap.parse_args(argv)
    from tools.envfile import load_env
    load_env()
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("[purge_contacts] DATABASE_URL 이 비어 있어 건너뜀(.env 확인)")
        return 1
    try:
        ids = purge_contacts(dsn, apply=a.apply)
    except Exception as e:
        print(f"[purge_contacts] 실패({type(e).__name__}) → python tools/check_ai_env.py 로 DB 상태 확인")
        return 1
    verb = "지움" if a.apply else "지울 대상"
    print(f"[purge_contacts] {verb} {len(ids)}건" + (f": {', '.join(ids)}" if ids else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
