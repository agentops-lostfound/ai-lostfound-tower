"""시연 물건 상태 되돌리기 — LF-14 (docs/design/database.md).

한줄 설명: 반환 시연을 하면 물건이 "인계 대기"·"인계 완료"로 남는다. 시연 물건(A-W01~A-W07)을 다시 "본센터 보관"으로 돌려 놓아 시연을 반복할 수 있게 한다.

사용법 (저장소 폴더, .venv 켠 상태, 팀 DB 켜진 상태)
    python tools/reset_demo.py            # 바뀔 물건만 보여 줌(아무것도 바꾸지 않음)
    python tools/reset_demo.py --apply    # 실제로 되돌림

- 시연 물건(center/seed_demo.sql 의 A-W01~A-W07)만 건드린다. 진짜 접수 물건은 바꾸지 않는다
- 바꿀 때마다 item_status_log 에 changed_by='system' 으로 남긴다(기록은 지우지 않음)
- 반환 기록(return_case)은 지우지 않는다. 다음 시연은 새 사례 번호를 쓴다
- DATABASE_URL(비밀번호 포함)은 출력하지 않는다
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEMO_ITEMS = [f"A-W0{i}" for i in range(1, 8)]
HOME_STATUS = "본센터 보관"

SQL_LIST = "SELECT item_id, status FROM item WHERE item_id = ANY(%s) ORDER BY item_id FOR UPDATE"
SQL_SET = "UPDATE item SET status = %s, updated_at = now() WHERE item_id = %s"
SQL_LOG = "INSERT INTO item_status_log (item_id, from_status, to_status, changed_by) VALUES (%s, %s, %s, 'system')"


def reset_demo(dsn: str, apply: bool = False, connect: Callable | None = None) -> list[tuple[str, str]]:
    """되돌릴(apply=True 면 되돌린) 물건 목록 [(물건 번호, 원래 상태)] 를 돌려준다."""
    if connect is None:
        import psycopg
        connect = lambda d: psycopg.connect(d, connect_timeout=5)  # noqa: E731
    changed = []
    with connect(dsn) as conn:          # 거래 하나: 중간에 실패하면 전부 되돌림
        with conn.cursor() as cur:
            cur.execute(SQL_LIST, (DEMO_ITEMS,))
            for item_id, status in cur.fetchall():
                if status == HOME_STATUS:
                    continue
                changed.append((item_id, status))
                if apply:
                    cur.execute(SQL_SET, (HOME_STATUS, item_id))
                    cur.execute(SQL_LOG, (item_id, status, HOME_STATUS))
        if not apply:
            conn.rollback()             # 미리보기는 잠금만 풀고 아무것도 남기지 않음
    return changed


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="시연 물건 상태를 '본센터 보관'으로 되돌리기")
    ap.add_argument("--apply", action="store_true", help="실제로 되돌림(없으면 미리보기만)")
    a = ap.parse_args(argv)
    from tools.envfile import load_env
    load_env()
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("DATABASE_URL 이 비어 있습니다(.env 확인)")
        return 1
    try:
        changed = reset_demo(dsn, apply=a.apply)
    except Exception as e:   # 주소·비밀번호가 섞일 수 있어 원문은 찍지 않는다
        print(f"DB 접속·쓰기 실패({type(e).__name__}) → python tools/check_ai_env.py 로 DB 상태 확인")
        return 1
    if not changed:
        print(f"시연 물건 {len(DEMO_ITEMS)}개 모두 이미 '{HOME_STATUS}' 입니다")
        return 0
    for item_id, status in changed:
        print(f"{item_id}: {status} → {HOME_STATUS}")
    print("되돌렸습니다" if a.apply else "미리보기입니다. 실제로 되돌리려면 --apply 를 붙이세요")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
