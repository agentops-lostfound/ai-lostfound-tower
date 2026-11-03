"""DB 부품(PostgreSQL) — LF-8 연결 지점 (docs/design/database.md 5장).

한줄 설명: 관제탑이 물건 기록을 읽고(db_get_item) 상태를 바꾸는(db_set_status) 두 함수를 진짜 DB로 수행한다.

    from agents.backends import CompositeBackend
    from agents.db_part import PostgresDbPart
    be = CompositeBackend(db=PostgresDbPart(os.environ["DATABASE_URL"]))

- 필요: `pip install "psycopg[binary]"`, DB 켜기 `docker compose up -d` (center/schema.sql 자동 적용)
- 약속(docs/contracts/mcp_tools.md): 예외를 던지지 않는다. 읽기 실패·없음 → None, 쓰기 실패 → {"ok": False, "reason": ...}
- 상태를 바꿀 때마다 item_status_log 에 changed_by='tower' 로 남긴다(같은 거래 안에서)
- DATABASE_URL(비밀번호 포함)은 출력하지 않는다
"""
from __future__ import annotations

from typing import Callable

from agents.contracts import ITEM_STATUS, robot_result

SQL_GET_ITEM = (
    "SELECT item_id, status, category, features, private_features, object_id "
    "FROM item WHERE item_id = %s"
)
SQL_LOCK_ITEM = "SELECT status FROM item WHERE item_id = %s FOR UPDATE"
SQL_SET_STATUS = "UPDATE item SET status = %s, updated_at = now() WHERE item_id = %s"
SQL_LOG_STATUS = (
    "INSERT INTO item_status_log (item_id, from_status, to_status, changed_by) VALUES (%s, %s, %s, 'tower')"
)


def _default_connect(dsn: str):
    import psycopg   # 설치 안 된 PC에서도 이 파일 import 는 되게 안에서 부른다
    return psycopg.connect(dsn, connect_timeout=5)


class PostgresDbPart:
    """CompositeBackend(db=...) 에 꽂는 DB 부품."""

    def __init__(self, dsn: str, connect: Callable | None = None):
        if not dsn:
            raise ValueError("DATABASE_URL 이 비어 있습니다(.env 확인)")
        self._dsn = dsn
        self._connect = connect or _default_connect
        self.last_error: str = ""   # 마지막 실패 종류(값·주소는 담지 않음)

    def __repr__(self) -> str:   # 비밀번호가 찍히지 않게
        return "PostgresDbPart(dsn=***)"

    def db_get_item(self, item_id: str) -> dict | None:
        try:
            with self._connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute(SQL_GET_ITEM, (item_id,))
                row = cur.fetchone()
        except Exception as e:
            self.last_error = type(e).__name__
            return None
        if row is None:
            return None
        iid, status, category, features, private, object_id = row
        return {"item_id": iid, "status": status, "category": category,
                "features": {**(features or {}), **(private or {})},   # 흐름·매칭은 둘 다 씀. MCP는 public_card 로 거름
                "object_id": object_id}

    def db_set_status(self, item_id: str, status: str) -> dict:
        if status not in ITEM_STATUS:
            return robot_result(False, f"모르는 상태: {status}")
        try:
            with self._connect(self._dsn) as conn:   # with 블록 = 거래 하나(끝나면 commit, 예외면 rollback)
                with conn.cursor() as cur:
                    cur.execute(SQL_LOCK_ITEM, (item_id,))
                    row = cur.fetchone()
                    if row is None:
                        return robot_result(False, "물건 기록 없음")
                    cur.execute(SQL_SET_STATUS, (status, item_id))
                    cur.execute(SQL_LOG_STATUS, (item_id, row[0], status))
            return robot_result(True)
        except Exception as e:
            self.last_error = type(e).__name__
            return robot_result(False, f"DB 쓰기 실패({type(e).__name__})")


__all__ = ["PostgresDbPart", "SQL_GET_ITEM", "SQL_LOCK_ITEM", "SQL_SET_STATUS", "SQL_LOG_STATUS"]
