"""찾기 요청 저장소 — 웹과 관제탑의 2단계 연결 (docs/design/architecture.md 3-2, 11/3 결정).

한줄 설명: 분실인이 웹에서 끝낸 확인(동의·신분증 OCR·확인 질문)과 수령 예약을 저장해 두고,
본센터 방문 때 직원 화면이 찾기 번호만 주면 관제탑이 그 결과를 읽어 반환 관문에 쓴다.

- 웹이 "통과했다"고 직원이 손으로 다시 입력하지 않는다 → 웹 결과는 저장된 값만 믿는다
- 개인정보: 이름·신분증 번호는 **가린 값**(* 포함)만 받는다. 전화·주민번호·이메일 모양이 보이면 거부
- 표: center/schema.sql 의 claim · quiz_attempt · reservation (+ claim.id_verified, 마이그레이션 002)
"""
from __future__ import annotations

import copy
import re
import threading
from datetime import date, datetime, timezone
from typing import Callable, Protocol

from agents.contracts import CLAIM_ID_RE, ITEM_ID_RE, validate_description

QUIZ_FIELDS = ["mark", "visible_text", "place", "color", "shape"]   # schema.sql quiz_attempt.field 와 같게
CLAIM_FIELDS = {"consent", "name_masked", "id_no_masked", "id_verified", "description", "lost_line",
                "lost_station", "lost_date", "item_id", "quiz", "visit_date"}
_PII = [re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}"),        # 전화번호
        re.compile(r"\d{6}[-\s]?[1-4]\d{6}"),                        # 주민등록번호
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")]                      # 이메일


def has_pii(text: str) -> bool:
    """전화번호·주민등록번호·이메일 모양이 있으면 True (장소·설명 같은 자유 입력 칸 검사용, 11/4)."""
    return any(p.search(text or "") for p in _PII)


class ClaimError(ValueError):
    """찾기 요청 형식 오류(HTTP 422)."""


def _date(v, key: str) -> str:
    try:
        return date.fromisoformat(v).isoformat()
    except (TypeError, ValueError):
        raise ClaimError(f"{key}: YYYY-MM-DD 형식") from None


def _masked(v, key: str) -> str:
    if not isinstance(v, str) or not (1 <= len(v) <= 32) or "*" not in v:
        raise ClaimError(f"{key}: 가린 값만(예: 변*원, 1*****) 32자 이하")
    if any(p.search(v) for p in _PII):
        raise ClaimError(f"{key}: 개인정보 원문으로 보여 받지 않습니다")
    return v


def parse_claim(payload: object) -> dict:
    """웹이 보낸 JSON → 저장할 찾기 요청. 잘못되면 ClaimError."""
    if not isinstance(payload, dict):
        raise ClaimError("JSON 객체여야 합니다")
    unknown = sorted(set(payload) - CLAIM_FIELDS)
    if unknown:
        raise ClaimError(f"모르는 칸: {unknown}")
    if payload.get("consent") is not True:
        raise ClaimError("consent: 필수 동의(true)가 없으면 찾기 요청을 만들지 않습니다")
    if not isinstance(payload.get("id_verified"), bool):
        raise ClaimError("id_verified: true/false")
    item_id = payload.get("item_id")
    if not isinstance(item_id, str) or not ITEM_ID_RE.match(item_id):
        raise ClaimError("item_id: 접수 번호 형식(예: A-20261103-0001)")
    desc = payload.get("description", {})
    if not isinstance(desc, dict) or not all(isinstance(v, str) for v in desc.values()):
        raise ClaimError("description: {칸: 글자} 형식")
    if any(has_pii(v) for v in desc.values()):     # 11/4: 확인 질문 답 등에 전화번호를 쓰면 설명에 저장되던 문제
        raise ClaimError("description: 전화번호·주민등록번호·이메일 같은 개인정보는 설명에 쓰지 않습니다")
    errs = validate_description(desc)
    if errs:
        raise ClaimError("description: " + "; ".join(errs))
    quiz = payload.get("quiz", [])
    if not isinstance(quiz, list) or not quiz:
        raise ClaimError("quiz: 확인 질문 결과가 1개 이상 필요 [{field, passed}]")
    for q in quiz:
        if not isinstance(q, dict) or set(q) != {"field", "passed"} or q["field"] not in QUIZ_FIELDS \
                or not isinstance(q["passed"], bool):
            raise ClaimError(f"quiz: {{field: {QUIZ_FIELDS} 중 하나, passed: true/false}} 만")
    out = {"name_masked": _masked(payload.get("name_masked"), "name_masked"),
           "id_no_masked": _masked(payload.get("id_no_masked"), "id_no_masked"),
           "id_verified": payload["id_verified"], "description": dict(desc), "item_id": item_id,
           "quiz": [dict(q) for q in quiz], "visit_date": _date(payload.get("visit_date"), "visit_date"),
           "lost_date": _date(payload["lost_date"], "lost_date") if payload.get("lost_date") else None}
    for key in ("lost_line", "lost_station"):
        v = payload.get(key)
        if v is not None and (not isinstance(v, str) or len(v) > 32):
            raise ClaimError(f"{key}: 32자 이하 글자")
        out[key] = v
    return out


def web_gates(row: dict) -> dict:
    """저장된 찾기 요청 → 반환 관문 3개(웹에서 생기는 것). 확인 질문은 모두 맞아야 통과."""
    quiz = row.get("quiz") or []
    return {"consent": bool(row.get("consented_at")), "id_verified": bool(row.get("id_verified")),
            "quiz_passed": bool(quiz) and all(q["passed"] for q in quiz)}


def public_view(row: dict) -> dict:
    """직원 화면·웹에 돌려줄 값(가린 이름, 물건 번호, 예약, 웹 관문). 설명·신분증 번호는 빼고 돌려준다."""
    return {"claim_id": row["claim_id"], "item_id": row["item_id"], "visit_date": row["visit_date"],
            "status": row["status"], "name_masked": row["name_masked"], "web_gates": web_gates(row),
            "created_at": row["created_at"]}


class ClaimStore(Protocol):
    def create(self, claim: dict, today: date | None = None) -> dict: ...
    def get(self, claim_id: str) -> dict | None: ...
    def mark_visited(self, claim_id: str) -> None: ...


class MemoryClaimStore:
    """프로그램이 켜져 있는 동안만 기억(시연·시험용)."""

    def __init__(self):
        self._rows: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, claim: dict, today: date | None = None) -> dict:
        day = (today or date.today()).strftime("%Y%m%d")
        with self._lock:
            seq = 1 + sum(1 for k in self._rows if k.startswith(f"C-{day}-"))
            cid = f"C-{day}-{seq:04d}"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._rows[cid] = {**copy.deepcopy(claim), "claim_id": cid, "consented_at": now,
                               "status": "booked", "created_at": now}
            return copy.deepcopy(self._rows[cid])

    def get(self, claim_id: str) -> dict | None:
        with self._lock:
            row = self._rows.get(claim_id)
            return copy.deepcopy(row) if row else None

    def mark_visited(self, claim_id: str) -> None:
        with self._lock:
            if claim_id in self._rows:
                self._rows[claim_id]["status"] = "visited"


SQL_NEXT_SEQ = ("SELECT COALESCE(MAX(CAST(RIGHT(claim_id, 4) AS INTEGER)), 0) + 1 FROM claim "
                "WHERE claim_id LIKE %s")
SQL_LOCK = "LOCK TABLE claim IN SHARE ROW EXCLUSIVE MODE"   # 같은 순번을 두 요청이 받지 않게
SQL_ITEM_EXISTS = "SELECT 1 FROM item WHERE item_id = %s"
SQL_INSERT_CLAIM = (
    "INSERT INTO claim (claim_id, consented_at, name_masked, id_no_masked, id_verified, description, "
    "lost_line, lost_station, lost_date) VALUES (%s, now(), %s, %s, %s, %s::jsonb, %s, %s, %s)"
)
SQL_INSERT_QUIZ = "INSERT INTO quiz_attempt (claim_id, item_id, field, passed) VALUES (%s, %s, %s, %s)"
SQL_INSERT_RESERVATION = "INSERT INTO reservation (claim_id, item_id, visit_date) VALUES (%s, %s, %s)"
SQL_GET = (
    "SELECT c.claim_id, c.consented_at, c.name_masked, c.id_verified, c.id_no_masked, r.item_id, r.visit_date, r.status, "
    "c.created_at FROM claim c JOIN reservation r ON r.claim_id = c.claim_id WHERE c.claim_id = %s"
)
SQL_GET_QUIZ = "SELECT field, passed FROM quiz_attempt WHERE claim_id = %s ORDER BY id"
SQL_VISITED = "UPDATE reservation SET status = 'visited' WHERE claim_id = %s"


def _iso(v):
    return v.isoformat(timespec="seconds") if isinstance(v, datetime) else (v.isoformat() if hasattr(v, "isoformat") else v)


class PostgresClaimStore:
    """PostgreSQL 저장(claim + quiz_attempt + reservation 을 거래 하나로)."""

    def __init__(self, dsn: str, connect: Callable | None = None):
        if not dsn:
            raise ValueError("DATABASE_URL 이 비어 있습니다(.env 확인)")
        self._dsn = dsn
        if connect is None:
            def connect(d):
                import psycopg
                return psycopg.connect(d, connect_timeout=5)
        self._connect = connect

    def __repr__(self) -> str:
        return "PostgresClaimStore(dsn=***)"

    def create(self, claim: dict, today: date | None = None) -> dict:
        import json
        day = (today or date.today()).strftime("%Y%m%d")
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_ITEM_EXISTS, (claim["item_id"],))
            if cur.fetchone() is None:
                raise ClaimError(f"item_id: 없는 물건 {claim['item_id']}")
            cur.execute(SQL_LOCK)
            cur.execute(SQL_NEXT_SEQ, (f"C-{day}-%",))
            cid = f"C-{day}-{int(cur.fetchone()[0]):04d}"
            cur.execute(SQL_INSERT_CLAIM, (cid, claim["name_masked"], claim["id_no_masked"], claim["id_verified"],
                                           json.dumps(claim["description"], ensure_ascii=False),
                                           claim.get("lost_line"), claim.get("lost_station"), claim.get("lost_date")))
            for q in claim["quiz"]:
                cur.execute(SQL_INSERT_QUIZ, (cid, claim["item_id"], q["field"], q["passed"]))
            cur.execute(SQL_INSERT_RESERVATION, (cid, claim["item_id"], claim["visit_date"]))
        return self.get(cid)

    def get(self, claim_id: str) -> dict | None:
        if not CLAIM_ID_RE.match(claim_id or ""):
            return None
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_GET, (claim_id,))
            row = cur.fetchone()
            if row is None:
                return None
            cols = ["claim_id", "consented_at", "name_masked", "id_verified", "id_no_masked", "item_id", "visit_date", "status",
                    "created_at"]
            d = {k: _iso(v) for k, v in zip(cols, row)}
            cur.execute(SQL_GET_QUIZ, (claim_id,))
            d["quiz"] = [{"field": f, "passed": bool(p)} for f, p in cur.fetchall()]
            return d

    def mark_visited(self, claim_id: str) -> None:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_VISITED, (claim_id,))


__all__ = ["ClaimError", "parse_claim", "web_gates", "public_view", "ClaimStore", "MemoryClaimStore",
           "PostgresClaimStore", "QUIZ_FIELDS"]
