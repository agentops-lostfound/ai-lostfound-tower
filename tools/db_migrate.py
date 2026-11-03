"""팀 DB 바뀐 점 적용 — LF-8 (docs/design/database.md).

한줄 설명: center/schema.sql 은 DB 를 처음 만들 때만 실행되므로, 그 뒤에 바뀐 점(center/migrations/*.sql)을 차례대로 한 번씩 적용한다.

사용법 (저장소 폴더, .venv 켠 상태, 팀 DB 켜진 상태)
    python tools/db_migrate.py            # 적용할 파일만 보여 줌(아무것도 바꾸지 않음)
    python tools/db_migrate.py --apply    # 실제로 적용(관제탑 켤 때 start_tower.bat 가 자동 실행)

- 적용한 파일 이름은 schema_migration 표에 남겨 두 번 적용하지 않는다
- 파일 하나 = 거래 하나(중간에 실패하면 그 파일은 통째로 되돌림)
- DB 가 막 켜지는 중이면 최대 wait 초 동안 다시 접속을 시도한다
- DATABASE_URL(비밀번호 포함)은 출력하지 않는다
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Callable

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MIGRATIONS = Path(__file__).resolve().parent.parent / "center" / "migrations"
SQL_TABLE = ("CREATE TABLE IF NOT EXISTS schema_migration ("
             "name VARCHAR(128) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
SQL_DONE = "SELECT name FROM schema_migration"
SQL_MARK = "INSERT INTO schema_migration (name) VALUES (%s)"


def pending(done: set[str], folder: Path = MIGRATIONS) -> list[Path]:
    return [p for p in sorted(folder.glob("*.sql")) if p.name not in done]


def _connect_retry(dsn: str, connect: Callable, wait: float):
    deadline = time.monotonic() + wait
    while True:
        try:
            return connect(dsn)
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def migrate(dsn: str, apply: bool = False, connect: Callable | None = None,
            folder: Path = MIGRATIONS, wait: float = 0) -> list[str]:
    """적용할(apply=True 면 적용한) 파일 이름 목록."""
    if connect is None:
        import psycopg
        connect = lambda d: psycopg.connect(d, connect_timeout=5)  # noqa: E731
    conn = _connect_retry(dsn, connect, wait)
    with conn:
        with conn.cursor() as cur:
            cur.execute(SQL_TABLE)
            cur.execute(SQL_DONE)
            done = {r[0] for r in cur.fetchall()}
        conn.commit()
        todo = pending(done, folder)
        if not apply:
            return [p.name for p in todo]
        for p in todo:
            with conn.cursor() as cur:
                cur.execute(p.read_text(encoding="utf-8"))
                cur.execute(SQL_MARK, (p.name,))
            conn.commit()
    return [p.name for p in todo]


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="팀 DB 바뀐 점(center/migrations) 적용")
    ap.add_argument("--apply", action="store_true", help="실제로 적용(없으면 미리보기만)")
    ap.add_argument("--wait", type=float, default=0, help="DB 가 켜질 때까지 기다릴 초(start_tower.bat 는 60)")
    a = ap.parse_args(argv)
    from tools.envfile import load_env
    load_env()
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("[db_migrate] DATABASE_URL 이 비어 있어 건너뜀(.env 확인)")
        return 1
    try:
        names = migrate(dsn, apply=a.apply, wait=a.wait)
    except Exception as e:   # 주소·비밀번호가 섞일 수 있어 원문은 찍지 않는다
        print(f"[db_migrate] 실패({type(e).__name__}) → python tools/check_ai_env.py 로 DB 상태 확인")
        return 1
    if not names:
        print("[db_migrate] 적용할 바뀐 점 없음(최신)")
    elif a.apply:
        print("[db_migrate] 적용함: " + ", ".join(names))
    else:
        print("[db_migrate] 적용할 파일: " + ", ".join(names) + " → 실제 적용은 --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
