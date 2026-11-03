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


class PostgresRecorder:
    """PostgreSQL 저장(뼈대). DB 연결 때 center/schema.sql 의 return_case·return_step 에 INSERT/SELECT 를 채운다."""

    def __init__(self, dsn: str):
        self.dsn = dsn   # .env DATABASE_URL — 출력하지 않는다

    def save(self, item_id: str, outcome: dict) -> None:
        raise NotImplementedError("DB 연결 때 구현(LF-8과 표 이름 맞춘 뒤)")

    def get(self, case_id: str) -> dict | None:
        raise NotImplementedError

    def has(self, case_id: str) -> bool:
        raise NotImplementedError

    def recent(self, limit: int = 20) -> list[dict]:
        raise NotImplementedError


__all__ = ["Recorder", "MemoryRecorder", "PostgresRecorder", "to_record"]
