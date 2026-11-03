"""습득물 접수 — 등록기계 화면(태블릿)이 부르는 관제탑 입구 (LF-8·LF-2, 11/3).

한줄 설명: 습득자가 등록기계에서 물건을 넣고 장소·연락처(선택)를 고르면 접수 번호를 발급해 DB에 남기고,
뒤에서 Qwen 이 사진을 분석하면 그 특징을 같은 물건 기록에 채운다.

화면 흐름(4장): 물건 넣기·촬영 → 어디서 주웠나(추천 + 직접 입력, 필수) → 연락처(이름·전화, 둘 다 선택) → 접수 번호
- 습득자는 Qwen 분석(물건당 수십 초)을 기다리지 않는다: 접수 번호를 먼저 주고, 특징은 set_features 로 나중에 채운다
- 연락처는 finder_contact 표에만 저장한다. 응답·로그·디스코드에 나가지 않는다. 둘 다 비면 저장하지 않는다(저장 = 동의)
- 발견 시각은 받지 않는다(MVP: 접수 시각 received_at 으로 대신, 11/3)
- 표: center/schema.sql 의 machine · place · item · finder_contact · item_status_log
"""
from __future__ import annotations

import copy
import json
import re
import threading
from datetime import date, datetime, timezone
from typing import Callable, Protocol

from agents.contracts import ITEM_ID_RE, MACHINE_LETTERS, UNKNOWN, make_item_id

INTAKE_FIELDS = {"machine_id", "place_id", "place_text", "finder", "photo_path"}
PHONE_RE = re.compile(r"^0\d{1,2}-?\d{3,4}-?\d{4}$")
PHOTO_RE = re.compile(r"^[A-Za-z0-9_./-]{1,256}$")
PUBLIC_KEYS = ("color", "shape", "material", "confidence")      # item.features
PRIVATE_KEYS = ("mark", "visible_text")                        # item.private_features (확인 질문 정답)
FIRST_STATUS = "등록기계 보관"


class IntakeError(ValueError):
    """접수 요청 형식 오류(HTTP 422)."""


def _text(v, key: str, limit: int, required: bool = False) -> str | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise IntakeError(f"{key}: 필수")
        return None
    if not isinstance(v, str) or len(v.strip()) > limit:
        raise IntakeError(f"{key}: {limit}자 이하 글자")
    return v.strip()


def parse_intake(payload: object) -> dict:
    """등록기계 화면이 보낸 JSON → 저장할 접수. 잘못되면 IntakeError."""
    if not isinstance(payload, dict):
        raise IntakeError("JSON 객체여야 합니다")
    unknown = sorted(set(payload) - INTAKE_FIELDS)
    if unknown:
        raise IntakeError(f"모르는 칸: {unknown} (발견 시각·물건 특징은 받지 않습니다)")
    machine = payload.get("machine_id")
    if machine not in MACHINE_LETTERS:
        raise IntakeError(f"machine_id: {list(MACHINE_LETTERS)} 중 하나")
    place_id = payload.get("place_id")
    if place_id is not None and (isinstance(place_id, bool) or not isinstance(place_id, int) or place_id < 1):
        raise IntakeError("place_id: 추천 장소 번호(1 이상 정수) 또는 비움")
    place_text = _text(payload.get("place_text"), "place_text", 128, required=True)
    finder = payload.get("finder")
    contact = None
    if finder is not None:
        if not isinstance(finder, dict) or set(finder) - {"name", "phone"}:
            raise IntakeError("finder: {name, phone} 만(둘 다 선택)")
        name = _text(finder.get("name"), "finder.name", 32)
        phone = _text(finder.get("phone"), "finder.phone", 20)
        if phone is not None and not PHONE_RE.match(phone):
            raise IntakeError("finder.phone: 전화번호 형식(예: 010-1234-5678)")
        if name or phone:
            contact = {"name": name, "phone": phone}
    photo = payload.get("photo_path")
    if photo is not None and (not isinstance(photo, str) or not PHOTO_RE.match(photo) or ".." in photo
                              or photo.startswith("/")):
        raise IntakeError("photo_path: 사진 파일 상대 경로(영문·숫자·_ . / -)")
    return {"machine_id": machine, "place_id": place_id, "place_text": place_text, "finder": contact,
            "photo_path": photo}


def receipt(row: dict) -> dict:
    """습득자 화면에 돌려줄 값(접수 번호·시각·장소). 연락처는 저장 여부만."""
    return {"item_id": row["item_id"], "received_at": row["received_at"], "status": row["status"],
            "place_text": row["place_text"], "contact_saved": bool(row.get("contact_saved"))}


def split_features(feats: dict) -> tuple[str, dict, dict]:
    """계약 특징(vision_adapter.to_features 결과) → (category, 공개 특징, 비공개 특징). DB CHECK 와 같은 나눔."""
    if not isinstance(feats, dict):
        raise IntakeError("features: 객체여야 합니다")
    return (feats.get("category") or UNKNOWN,
            {k: feats[k] for k in PUBLIC_KEYS if k in feats},
            {k: feats[k] for k in PRIVATE_KEYS if k in feats})


def parse_features(payload: object) -> dict:
    """Qwen 결과 → 계약 특징. 본문: {"qwen": general_items_v1 특징, "confidence": 0~1(선택)}"""
    from agents.vision_adapter import to_features
    if not isinstance(payload, dict) or set(payload) - {"qwen", "confidence"} or not isinstance(payload.get("qwen"), dict):
        raise IntakeError('본문: {"qwen": {...Qwen 특징...}, "confidence": 0~1}')
    conf = payload.get("confidence", 0.9)
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise IntakeError("confidence: 0~1 숫자")
    return to_features(payload["qwen"], conf)


class IntakeStore(Protocol):
    def places(self, machine_id: str, limit: int = 10) -> list[dict]: ...
    def create(self, intake: dict, today: date | None = None) -> dict: ...
    def set_features(self, item_id: str, feats: dict) -> bool: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MemoryIntakeStore:
    """프로그램이 켜져 있는 동안만 기억(시연·시험용). 장소 추천은 DEMO_PLACES."""

    def __init__(self, places: dict[str, list[str]] | None = None):
        self._lock = threading.Lock()
        self._places: list[dict] = []
        for machine, labels in (places if places is not None else DEMO_PLACES).items():
            for label in labels:
                self._places.append({"place_id": len(self._places) + 1, "machine_id": machine, "label": label,
                                     "use_count": 0})
        self.items: dict[str, dict] = {}
        self.contacts: dict[str, dict] = {}     # 시험에서 저장 여부 확인용(응답으로 나가지 않음)

    def places(self, machine_id: str, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = [p for p in self._places if p["machine_id"] == machine_id]
            rows.sort(key=lambda p: (-p["use_count"], p["place_id"]))
            return [{"place_id": p["place_id"], "label": p["label"]} for p in rows[:limit]]

    def create(self, intake: dict, today: date | None = None) -> dict:
        day = today or date.today()
        with self._lock:
            if intake["place_id"] is not None:
                p = next((p for p in self._places if p["place_id"] == intake["place_id"]
                          and p["machine_id"] == intake["machine_id"]), None)
                if p is None:
                    raise IntakeError("place_id: 이 등록기계의 추천 장소가 아닙니다")
                p["use_count"] += 1
            prefix = f"{MACHINE_LETTERS[intake['machine_id']]}-{day:%Y%m%d}-"
            seq = 1 + sum(1 for k in self.items if k.startswith(prefix))
            item_id = make_item_id(intake["machine_id"], day, seq)
            row = {"item_id": item_id, "machine_id": intake["machine_id"], "place_id": intake["place_id"],
                   "place_text": intake["place_text"], "photo_path": intake["photo_path"], "received_at": _now(),
                   "status": FIRST_STATUS, "category": UNKNOWN, "features": {}, "private_features": {},
                   "contact_saved": intake["finder"] is not None}
            self.items[item_id] = row
            if intake["finder"]:
                self.contacts[item_id] = dict(intake["finder"])
            return copy.deepcopy(row)

    def set_features(self, item_id: str, feats: dict) -> bool:
        cat, pub, priv = split_features(feats)
        with self._lock:
            row = self.items.get(item_id)
            if row is None:
                return False
            row.update(category=cat, features=pub, private_features=priv)
            return True


# 시연용 추천 장소(PostgreSQL 은 center/migrations/003 에 같은 목록)
DEMO_PLACES = {
    "KIOSK-A": ["해운대역 승강장", "대합실·개찰구 주변", "화장실", "엘리베이터·에스컬레이터", "열차 안", "출구 주변"],
    "KIOSK-B": ["중앙역 승강장", "대합실·개찰구 주변", "화장실", "엘리베이터·에스컬레이터", "열차 안", "출구 주변"],
}

SQL_MACHINE = "SELECT line, station FROM machine WHERE machine_id = %s"
SQL_PLACES = ("SELECT place_id, label FROM place WHERE line = %s AND station = %s "
              "ORDER BY use_count DESC, place_id LIMIT %s")
SQL_PLACE_OK = "SELECT 1 FROM place WHERE place_id = %s AND line = %s AND station = %s"
SQL_PLACE_USE = "UPDATE place SET use_count = use_count + 1 WHERE place_id = %s"
SQL_LOCK_ITEM = "LOCK TABLE item IN SHARE ROW EXCLUSIVE MODE"   # 같은 순번을 두 요청이 받지 않게
SQL_NEXT_ITEM_SEQ = ("SELECT COALESCE(MAX(CAST(RIGHT(item_id, 4) AS INTEGER)), 0) + 1 FROM item "
                     "WHERE item_id LIKE %s")
SQL_INSERT_ITEM = ("INSERT INTO item (item_id, machine_id, place_id, place_text, photo_path) "
                   "VALUES (%s, %s, %s, %s, %s) RETURNING received_at, status")
SQL_INSERT_CONTACT = "INSERT INTO finder_contact (item_id, name, phone) VALUES (%s, %s, %s)"
SQL_LOG_FIRST = ("INSERT INTO item_status_log (item_id, from_status, to_status, changed_by) "
                 "VALUES (%s, NULL, %s, 'kiosk')")
SQL_SET_FEATURES = ("UPDATE item SET category = %s, features = %s::jsonb, private_features = %s::jsonb, "
                    "updated_at = now() WHERE item_id = %s")


def _iso(v):
    return v.isoformat(timespec="seconds") if isinstance(v, datetime) else v


class PostgresIntakeStore:
    """PostgreSQL 저장(item + finder_contact + 상태 기록을 거래 하나로)."""

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
        return "PostgresIntakeStore(dsn=***)"

    def _station(self, cur, machine_id: str):
        cur.execute(SQL_MACHINE, (machine_id,))
        row = cur.fetchone()
        if row is None:
            raise IntakeError(f"machine_id: DB 에 없는 등록기계 {machine_id}")
        return row

    def places(self, machine_id: str, limit: int = 10) -> list[dict]:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            line, station = self._station(cur, machine_id)
            if line is None:
                return []
            cur.execute(SQL_PLACES, (line, station, limit))
            return [{"place_id": pid, "label": label} for pid, label in cur.fetchall()]

    def create(self, intake: dict, today: date | None = None) -> dict:
        day = today or date.today()
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            line, station = self._station(cur, intake["machine_id"])
            if intake["place_id"] is not None:
                cur.execute(SQL_PLACE_OK, (intake["place_id"], line, station))
                if cur.fetchone() is None:
                    raise IntakeError("place_id: 이 등록기계의 추천 장소가 아닙니다")
                cur.execute(SQL_PLACE_USE, (intake["place_id"],))
            cur.execute(SQL_LOCK_ITEM)
            cur.execute(SQL_NEXT_ITEM_SEQ, (f"{MACHINE_LETTERS[intake['machine_id']]}-{day:%Y%m%d}-%",))
            item_id = make_item_id(intake["machine_id"], day, int(cur.fetchone()[0]))
            cur.execute(SQL_INSERT_ITEM, (item_id, intake["machine_id"], intake["place_id"], intake["place_text"],
                                          intake["photo_path"]))
            received_at, status = cur.fetchone()
            if intake["finder"]:
                cur.execute(SQL_INSERT_CONTACT, (item_id, intake["finder"]["name"], intake["finder"]["phone"]))
            cur.execute(SQL_LOG_FIRST, (item_id, status))
        return {"item_id": item_id, "machine_id": intake["machine_id"], "place_text": intake["place_text"],
                "received_at": _iso(received_at), "status": status, "contact_saved": intake["finder"] is not None}

    def set_features(self, item_id: str, feats: dict) -> bool:
        cat, pub, priv = split_features(feats)
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_SET_FEATURES, (cat, json.dumps(pub, ensure_ascii=False),
                                           json.dumps(priv, ensure_ascii=False), item_id))
            return cur.rowcount == 1


def valid_item_id(item_id: str) -> bool:
    return bool(ITEM_ID_RE.match(item_id or ""))


__all__ = ["IntakeError", "parse_intake", "parse_features", "receipt", "split_features", "IntakeStore",
           "MemoryIntakeStore", "PostgresIntakeStore", "DEMO_PLACES", "valid_item_id"]
