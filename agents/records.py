"""반환 기록 저장소 — LF-14 (docs/design/erd.md RETURN_CASE · RETURN_STEP, 관제탑 소유).

한줄 설명: 반환 흐름이 끝날 때마다 "어떤 사례가 어떤 결정으로 끝났는지"를 남긴다. 개인정보 칼럼은 없다.

- 지금은 메모리 저장(MemoryRecorder, 프로그램을 끄면 사라짐). PostgreSQL 저장은 DB 연결 때 PostgresRecorder 를 채운다.
- 표 정의: center/schema.sql 의 return_case · return_step (같은 PostgreSQL, 관제탑 소유. 물건 표 item 은 DB 담당 정연우 LF-8)
"""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone
from typing import Protocol


class Recorder(Protocol):
    def save(self, item_id: str, outcome: dict) -> None: ...
    def get(self, case_id: str) -> dict | None: ...
    def has(self, case_id: str) -> bool: ...
    def recent(self, limit: int = 20) -> list[dict]: ...


def to_record(item_id: str, outcome: dict, now: datetime | None = None) -> dict:
    """Outcome → RETURN_CASE 한 줄 + RETURN_STEP 목록(표 칼럼 이름 그대로)."""
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return {
        "case_id": outcome["case_id"], "item_id": item_id, "decision": outcome["decision"],
        "reason": outcome["reason"], "approved": bool(outcome.get("approved")),
        "matched_object": outcome.get("matched_object"), "seconds": outcome.get("seconds", 0.0),
        "created_at": at,
        "steps": [{"step": s, "at": at} for s in outcome.get("steps", [])],
    }


class MemoryRecorder:
    """프로그램이 켜져 있는 동안만 기억(시연·시험용)."""

    def __init__(self):
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def save(self, item_id: str, outcome: dict) -> None:
        with self._lock:
            if outcome["case_id"] in self._rows:
                raise KeyError(f"이미 기록된 사례: {outcome['case_id']}")
            self._rows[outcome["case_id"]] = to_record(item_id, outcome)

    def get(self, case_id: str) -> dict | None:
        with self._lock:
            row = self._rows.get(case_id)
            return copy.deepcopy(row) if row else None

    def has(self, case_id: str) -> bool:
        with self._lock:
            return case_id in self._rows

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = list(self._rows.values())[-limit:]
            return [{k: v for k, v in r.items() if k != "steps"} for r in reversed(rows)]


SQL_HAS = "SELECT 1 FROM return_case WHERE case_id = %s"
SQL_INSERT_CASE = (
    "INSERT INTO return_case (case_id, item_id, decision, reason, approved, matched_object, seconds) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s)"
)
SQL_INSERT_STEP = "INSERT INTO return_step (case_id, step) VALUES (%s, %s)"
SQL_GET_CASE = (
    "SELECT case_id, item_id, decision, reason, approved, matched_object, seconds, created_at "
    "FROM return_case WHERE case_id = %s"
)
SQL_GET_STEPS = "SELECT step, at FROM return_step WHERE case_id = %s ORDER BY id"
SQL_RECENT = (
    "SELECT case_id, item_id, decision, reason, approved, matched_object, seconds, created_at "
    "FROM return_case ORDER BY created_at DESC, case_id DESC LIMIT %s"
)
CASE_COLS = ["case_id", "item_id", "decision", "reason", "approved", "matched_object", "seconds", "created_at"]


def _row(cols: list[str], row) -> dict:
    d = dict(zip(cols, row))
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat(timespec="seconds")
    return d


class PostgresRecorder:
    """PostgreSQL 저장. center/schema.sql 의 return_case·return_step (관제탑 소유).

    - 같은 case_id 를 다시 저장하면 KeyError(메모리 저장과 같은 약속)
    - DB 연결 실패는 그대로 예외로 올린다 → 관제탑 서비스가 "기록 실패" 로 처리(반환 결과는 돌려줌)
    """

    def __init__(self, dsn: str, connect=None):
        if not dsn:
            raise ValueError("DATABASE_URL 이 비어 있습니다(.env 확인)")
        self._dsn = dsn   # .env DATABASE_URL — 출력하지 않는다
        if connect is None:
            def connect(d):
                import psycopg
                return psycopg.connect(d, connect_timeout=5)
        self._connect = connect

    def __repr__(self) -> str:
        return "PostgresRecorder(dsn=***)"

    def save(self, item_id: str, outcome: dict) -> None:
        rec = to_record(item_id, outcome)
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_HAS, (rec["case_id"],))
            if cur.fetchone() is not None:
                raise KeyError(f"이미 기록된 사례: {rec['case_id']}")
            cur.execute(SQL_INSERT_CASE, (rec["case_id"], rec["item_id"], rec["decision"], rec["reason"],
                                          rec["approved"], rec["matched_object"], rec["seconds"]))
            for st in rec["steps"]:
                cur.execute(SQL_INSERT_STEP, (rec["case_id"], st["step"]))

    def get(self, case_id: str) -> dict | None:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_GET_CASE, (case_id,))
            row = cur.fetchone()
            if row is None:
                return None
            d = _row(CASE_COLS, row)
            cur.execute(SQL_GET_STEPS, (case_id,))
            d["steps"] = [_row(["step", "at"], r) if not hasattr(r[1], "isoformat")
                          else {"step": r[0], "at": r[1].isoformat(timespec="seconds")} for r in cur.fetchall()]
            return d

    def has(self, case_id: str) -> bool:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_HAS, (case_id,))
            return cur.fetchone() is not None

    def recent(self, limit: int = 20) -> list[dict]:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_RECENT, (limit,))
            return [_row(CASE_COLS, r) for r in cur.fetchall()]


__all__ = ["Recorder", "MemoryRecorder", "PostgresRecorder", "to_record"]
