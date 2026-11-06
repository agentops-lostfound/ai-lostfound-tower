"""본센터 보관함 정답지 (LF-8 · 11/6 변재원)

한줄 설명: "물건 X 는 보관함 몇 행 몇 번 칸에 있고, 로봇팔은 어느 저장 자세(pose)로 가야 하는가"를 기억하고,
비전(김건태) run_storage_check.py 가 읽는 storage JSON 으로 내보낸다.

흐름: 등록기계 → 본센터 도착(본센터 보관) → 직원이 칸에 넣고 assign → YOLO 가 그 행만 잘라 개수 확인 → 로봇이 저장 자세로 집기
      → 인계 완료가 되면 칸이 자동으로 빈다(DB 트리거, 메모리 저장소는 읽을 때 거름). 인계 대기 동안은 칸 예약 유지(11/6 교차 검증)

배치(center/migrations/007_storage_slots_1106.sql 과 같음): 4행 × 2칸 = 8칸 + 인계 구역 H-1(제출보관함 20×20cm)
- 행별 품목은 판 사진에 맞춘 시연 시작값(009, 팀이 임의로 정함)이며 바꿀 수 있다. 모형폰 행(R1)은 폰 2개를 각각 사선으로 두고, 다른 행보다 칸 간격이 넓다(11/6 사진)
- 인계 구역 H-1(제출보관함)은 로봇팔 받침 반대쪽 긴 변 바깥(008 마이그레이션)
- 저장 자세 이름은 로봇 티칭에서 정한다. 티칭 전에는 None → 내보내기 warnings 에 표시(김건태 load_storage 가 거절)

용어
- 구역(section) = 보관판의 한 행. YOLO 가 잘라서 개수를 세는 단위
- 칸(slot) = 물건 하나 자리. 저장 자세 하나와 짝
- storage JSON = {"sections": {구역: {"slots": {"1": 자세}, "bounds_mm"?}}, "inventory": {물건번호: {"section", "slot"}}}
"""
from __future__ import annotations

import copy
import re
import threading
from datetime import datetime, timezone
from typing import Callable, Protocol

from agents.contracts import ITEM_ID_RE

# 김건태 run_storage_check.ON_SHELF 와 같음: 이 상태일 때만 보관함 위에 있다고 본다
ON_SHELF = ("본센터 보관", "확인 중", "승인·수령 예약")
RELEASE_STATUSES = ("인계 완료",)   # 11/6: 인계 대기 중에는 칸 예약 유지(교차 검증이 틀리면 원래 칸으로), 011 마이그레이션
CHECK_STATUSES = ("count_match", "count_mismatch", "verification_unavailable", "resolution_mismatch",
                  "invalid_calibration", "section_out_of_frame", "match_held")
POSE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SLOT_RE = re.compile(r"^[A-Z][0-9]?-[0-9]{1,2}$")

# (구역, 이름, 종류, 허용 품목, 칸 수, 칸 메모) — 007 시작값 + 008·009 사진 반영과 같게(tests/test_storage.py)
LAYOUT = [
    ("R1", "1행 모형폰", "shelf", ["모형폰"], 2, "사선 배치·간격 넓음"),
    ("R2", "2행 USB·핸드크림·보조배터리", "shelf", ["USB", "핸드크림", "보조배터리"], 2, None),
    ("R3", "3행 립밤", "shelf", ["립밤"], 2, None),
    ("R4", "4행 지갑", "shelf", ["지갑"], 2, None),
    ("H", "인계 구역(제출보관함)", "handover", [], 1, "20×20cm·로봇팔 반대쪽"),
]


class StorageError(ValueError):
    """잘못된 요청(없는 칸·형식 오류·품목 불일치) → 422/404"""

    def __init__(self, message: str, not_found: bool = False):
        super().__init__(message)
        self.not_found = not_found


class StorageConflict(Exception):
    """이미 다른 물건이 있는 칸 등 → 409"""


class StorageStore(Protocol):
    def layout(self) -> dict: ...
    def assign(self, item_id: str, slot_id: str, override_category: bool = False, by: str = "staff") -> dict: ...
    def release(self, item_id: str | None = None, slot_id: str | None = None) -> dict: ...
    def set_pose(self, slot_id: str, pose_name: str | None) -> dict: ...
    def record_check(self, check: dict) -> dict: ...
    def recent_checks(self, limit: int = 20) -> list[dict]: ...
    def export(self) -> dict: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def check_slot_id(slot_id: object) -> str:
    if not isinstance(slot_id, str) or not SLOT_RE.match(slot_id):
        raise StorageError("slot_id: R1-1 같은 칸 번호여야 합니다")
    return slot_id


def check_item_id(item_id: object) -> str:
    if not isinstance(item_id, str) or not ITEM_ID_RE.match(item_id):
        raise StorageError("item_id: 접수 번호 형식이 아닙니다")
    return item_id


def check_pose(pose: object) -> str | None:
    if pose is None or pose == "":
        return None
    if not isinstance(pose, str) or not POSE_RE.match(pose):
        raise StorageError("pose_name: 영문 소문자로 시작하는 이름(예: pose_1, shelf_r1_1)이어야 합니다")
    return pose


def parse_check(payload: object) -> dict:
    """탑뷰 개수 확인 결과(run_storage_check.py 출력 일부) → 기록할 칸만"""
    if not isinstance(payload, dict):
        raise StorageError("JSON 객체여야 합니다")
    unknown = sorted(set(payload) - {"section", "expected_count", "detected_count", "status", "item_id"})
    if unknown:
        raise StorageError(f"모르는 칸: {unknown}")
    if payload.get("status") not in CHECK_STATUSES:
        raise StorageError(f"status: {list(CHECK_STATUSES)} 중 하나")
    for key in ("expected_count", "detected_count"):
        v = payload.get(key)
        if v is None and key == "detected_count":
            continue
        if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= 99:
            raise StorageError(f"{key}: 0~99 정수")
    item_id = payload.get("item_id")
    return {"section": payload.get("section"), "expected_count": payload["expected_count"],
            "detected_count": payload.get("detected_count"), "status": payload["status"],
            "item_id": check_item_id(item_id) if item_id is not None else None}


def build_export(sections: list[dict], assignments: list[dict]) -> dict:
    """layout 행 + 보관 중 물건 → 김건태 storage JSON. 저장 자세가 빈 칸에 물건이 있으면 warnings 에 적는다."""
    out_sections, warnings = {}, []
    for s in sections:
        entry = {"label": s["label"], "kind": s["kind"],
                 "slots": {str(slot["slot_no"]): slot["pose_name"] for slot in s["slots"]}}
        if s.get("bounds_mm"):
            entry["bounds_mm"] = list(s["bounds_mm"])
        out_sections[s["code"]] = entry
    inventory = {}
    for a in sorted(assignments, key=lambda a: a["slot_id"]):
        if a["status"] not in ON_SHELF:
            continue
        inventory[a["item_id"]] = {"section": a["section"], "slot": str(a["slot_no"])}
        if not out_sections[a["section"]]["slots"].get(str(a["slot_no"])):
            warnings.append(f"{a['slot_id']}: 물건 {a['item_id']} 이 있지만 저장 자세가 비어 있음(로봇 티칭 필요)")
    return {"sections": out_sections, "inventory": inventory, "warnings": warnings, "exported_at": _now()}


def _category_ok(section: dict, category: str | None, override: bool) -> None:
    allowed = section["allowed_categories"]
    if section["kind"] == "handover":
        raise StorageError("인계 구역(H)은 로봇이 바구니로 옮길 때만 씁니다. 보관 칸(R1~R4)을 고르세요")
    # category None = 품목 정보가 없는 시연 부품(evaluation/test_cases.json) → 막지 않음. DB 의 '확인 불가'는 막음
    if allowed and category is not None and category not in allowed and not override:
        raise StorageError(f"{section['code']} 행은 {'·'.join(allowed)} 자리입니다(이 물건: {category}). "
                           "그래도 넣으려면 override_category: true")


class MemoryStorageStore:
    """프로그램이 켜져 있는 동안만 기억(시연·시험용). item_lookup(item_id) → {"status", "category"} | None"""

    def __init__(self, item_lookup: Callable[[str], dict | None] | None = None, layout=None):
        self._lock = threading.Lock()
        self._lookup = item_lookup
        self._sections: list[dict] = []
        for code, label, kind, allowed, n, note in (layout or LAYOUT):
            self._sections.append({"code": code, "label": label, "kind": kind, "allowed_categories": list(allowed),
                                   "bounds_mm": None,
                                   "slots": [{"slot_id": f"{code}-{i}", "slot_no": i, "pose_name": None, "note": note}
                                             for i in range(1, n + 1)]})
        self._assign: dict[str, dict] = {}       # slot_id → {"item_id", "assigned_at", "assigned_by"}
        self._checks: list[dict] = []

    def _slot(self, slot_id: str) -> tuple[dict, dict]:
        for s in self._sections:
            for slot in s["slots"]:
                if slot["slot_id"] == slot_id:
                    return s, slot
        raise StorageError(f"없는 칸: {slot_id}", not_found=True)

    def _item(self, item_id: str) -> dict:
        if self._lookup is None:
            return {"status": ON_SHELF[0], "category": None}
        item = self._lookup(item_id)
        if not item:
            raise StorageError(f"없는 물건: {item_id}", not_found=True)
        return item

    def _rows(self) -> list[dict]:
        rows = []
        for slot_id, a in self._assign.items():
            s, slot = self._slot(slot_id)
            item = (self._lookup(a["item_id"]) or {}) if self._lookup else {"status": ON_SHELF[0], "category": None}
            rows.append({"slot_id": slot_id, "section": s["code"], "slot_no": slot["slot_no"], "item_id": a["item_id"],
                         "status": item.get("status"), "category": item.get("category"),
                         "assigned_at": a["assigned_at"]})
        # 메모리 저장소는 트리거가 없으니 바구니로 나간 물건은 여기서 칸을 비운다
        for r in rows:
            if r["status"] in RELEASE_STATUSES:
                self._assign.pop(r["slot_id"], None)
        return [r for r in rows if r["status"] not in RELEASE_STATUSES]

    def layout(self) -> dict:
        with self._lock:
            rows = {r["slot_id"]: r for r in self._rows()}
            sections = copy.deepcopy(self._sections)
        return _layout_view(sections, rows)

    def assign(self, item_id: str, slot_id: str, override_category: bool = False, by: str = "staff") -> dict:
        check_item_id(item_id)
        check_slot_id(slot_id)
        with self._lock:
            self._rows()                          # 바구니로 나간 물건의 칸을 먼저 비움(트리거 대신)
            section, slot = self._slot(slot_id)
            item = self._item(item_id)
            if item.get("status") not in ON_SHELF:
                raise StorageConflict(f"{item_id} 은 '{item.get('status')}' 상태라 보관함에 넣을 수 없습니다"
                                      f"({'·'.join(ON_SHELF)}만)")
            _category_ok(section, item.get("category"), override_category)
            current = self._assign.get(slot_id)
            if current and current["item_id"] != item_id:
                raise StorageConflict(f"{slot_id} 에는 이미 {current['item_id']} 이 있습니다(먼저 비우기)")
            for sid, a in list(self._assign.items()):
                if a["item_id"] == item_id and sid != slot_id:
                    del self._assign[sid]      # 다른 칸에서 옮겨 옴
            self._assign[slot_id] = {"item_id": item_id, "assigned_at": _now(), "assigned_by": by}
            return {"ok": True, "item_id": item_id, "slot_id": slot_id, "section": section["code"],
                    "slot": str(slot["slot_no"]), "pose_name": slot["pose_name"]}

    def release(self, item_id: str | None = None, slot_id: str | None = None) -> dict:
        if (item_id is None) == (slot_id is None):
            raise StorageError("item_id 와 slot_id 중 하나만 보내세요")
        with self._lock:
            if slot_id is not None:
                check_slot_id(slot_id)
                self._slot(slot_id)
                a = self._assign.pop(slot_id, None)
                return {"ok": True, "slot_id": slot_id, "item_id": a["item_id"] if a else None}
            check_item_id(item_id)
            for sid, a in list(self._assign.items()):
                if a["item_id"] == item_id:
                    del self._assign[sid]
                    return {"ok": True, "slot_id": sid, "item_id": item_id}
            return {"ok": True, "slot_id": None, "item_id": item_id}

    def set_pose(self, slot_id: str, pose_name: str | None) -> dict:
        check_slot_id(slot_id)
        pose = check_pose(pose_name)
        with self._lock:
            _, slot = self._slot(slot_id)
            slot["pose_name"] = pose
            return {"ok": True, "slot_id": slot_id, "pose_name": pose}

    def set_bounds(self, section_code: str, bounds_mm: list | None) -> dict:
        b = _check_bounds(bounds_mm)
        with self._lock:
            s = next((s for s in self._sections if s["code"] == section_code), None)
            if s is None:
                raise StorageError(f"없는 구역: {section_code}", not_found=True)
            s["bounds_mm"] = b
            return {"ok": True, "section": section_code, "bounds_mm": b}

    def record_check(self, check: dict) -> dict:
        c = parse_check(check)
        with self._lock:
            if not any(s["code"] == c["section"] for s in self._sections):
                raise StorageError(f"없는 구역: {c['section']}", not_found=True)
            row = {"id": len(self._checks) + 1, **c, "at": _now()}
            self._checks.append(row)
            return dict(row)

    def recent_checks(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return [dict(r) for r in reversed(self._checks[-max(1, min(int(limit), 100)):])]

    def export(self) -> dict:
        with self._lock:
            rows = self._rows()
            sections = copy.deepcopy(self._sections)
        return build_export(sections, rows)


def _check_bounds(bounds) -> list | None:
    if bounds is None:
        return None
    if (not isinstance(bounds, list) or len(bounds) != 4
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in bounds)
            or bounds[0] >= bounds[2] or bounds[1] >= bounds[3]):
        raise StorageError("bounds_mm: [x1, y1, x2, y2] 숫자 4개(x1<x2, y1<y2)")
    return [float(v) for v in bounds]


def _layout_view(sections: list[dict], rows: dict[str, dict]) -> dict:
    """화면·API 용: 구역마다 칸과 들어 있는 물건"""
    total = used = missing_pose = 0
    for s in sections:
        for slot in s["slots"]:
            r = rows.get(slot["slot_id"])
            slot["item"] = ({"item_id": r["item_id"], "status": r["status"], "category": r["category"],
                             "assigned_at": r["assigned_at"]} if r else None)
            if s["kind"] == "shelf":
                total += 1
                used += r is not None
                missing_pose += slot["pose_name"] is None
    return {"sections": sections, "summary": {"shelf_slots": total, "used": used, "free": total - used,
                                              "slots_without_pose": missing_pose}}


# ---------- PostgreSQL ----------
SQL_SECTIONS = ("SELECT section_code, label, kind, allowed_categories, bounds_mm FROM storage_section "
                "ORDER BY sort_order, section_code")
SQL_SLOTS = "SELECT slot_id, section_code, slot_no, pose_name, note FROM storage_slot ORDER BY section_code, slot_no"
SQL_ROWS = ("SELECT a.slot_id, s.section_code, s.slot_no, a.item_id, i.status, i.category, a.assigned_at "
            "FROM storage_assignment a JOIN storage_slot s USING (slot_id) JOIN item i USING (item_id) "
            "ORDER BY a.slot_id")
SQL_SLOT_ONE = ("SELECT s.slot_id, s.section_code, s.slot_no, s.pose_name, sec.kind, sec.allowed_categories "
                "FROM storage_slot s JOIN storage_section sec USING (section_code) WHERE s.slot_id = %s")
SQL_ITEM_LOCK = "SELECT status, category FROM item WHERE item_id = %s FOR UPDATE"
SQL_SLOT_LOCK = "SELECT item_id FROM storage_assignment WHERE slot_id = %s FOR UPDATE"
SQL_MOVE_OUT = "DELETE FROM storage_assignment WHERE item_id = %s AND slot_id <> %s"
SQL_ASSIGN = ("INSERT INTO storage_assignment (slot_id, item_id, assigned_by) VALUES (%s, %s, %s) "
              "ON CONFLICT (slot_id) DO NOTHING RETURNING slot_id")
SQL_RELEASE_SLOT = "DELETE FROM storage_assignment WHERE slot_id = %s RETURNING item_id"
SQL_RELEASE_ITEM = "DELETE FROM storage_assignment WHERE item_id = %s RETURNING slot_id"
SQL_SET_POSE = "UPDATE storage_slot SET pose_name = %s WHERE slot_id = %s RETURNING slot_id"
SQL_SET_BOUNDS = "UPDATE storage_section SET bounds_mm = %s::jsonb WHERE section_code = %s RETURNING section_code"
SQL_CHECK = ("INSERT INTO inventory_check (section_code, item_id, expected_count, detected_count, status) "
             "VALUES (%s, %s, %s, %s, %s) RETURNING id, at")
SQL_CHECKS = ("SELECT id, section_code, item_id, expected_count, detected_count, status, at FROM inventory_check "
              "ORDER BY id DESC LIMIT %s")
SQL_SECTION_EXISTS = "SELECT 1 FROM storage_section WHERE section_code = %s"


def _iso(v) -> str | None:
    return v.isoformat(timespec="seconds") if hasattr(v, "isoformat") else (str(v) if v is not None else None)


class PostgresStorageStore:
    """PostgreSQL 저장(storage_section · storage_slot · storage_assignment · inventory_check, 007 마이그레이션)"""

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
        return "PostgresStorageStore(dsn=***)"

    def _read(self, cur) -> tuple[list[dict], list[dict]]:
        cur.execute(SQL_SECTIONS)
        sections = [{"code": c, "label": lb, "kind": k, "allowed_categories": list(al or []), "bounds_mm": b,
                     "slots": []} for c, lb, k, al, b in cur.fetchall()]
        by_code = {s["code"]: s for s in sections}
        cur.execute(SQL_SLOTS)
        for slot_id, code, no, pose, note in cur.fetchall():
            by_code[code]["slots"].append({"slot_id": slot_id, "slot_no": no, "pose_name": pose, "note": note})
        cur.execute(SQL_ROWS)
        rows = [{"slot_id": sid, "section": code, "slot_no": no, "item_id": iid, "status": st, "category": cat,
                 "assigned_at": _iso(at)} for sid, code, no, iid, st, cat, at in cur.fetchall()]
        return sections, rows

    def layout(self) -> dict:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            sections, rows = self._read(cur)
        return _layout_view(sections, {r["slot_id"]: r for r in rows})

    def export(self) -> dict:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            sections, rows = self._read(cur)
        return build_export(sections, rows)

    def assign(self, item_id: str, slot_id: str, override_category: bool = False, by: str = "staff") -> dict:
        check_item_id(item_id)
        check_slot_id(slot_id)
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_SLOT_ONE, (slot_id,))
            row = cur.fetchone()
            if row is None:
                raise StorageError(f"없는 칸: {slot_id}", not_found=True)
            _, code, no, pose, kind, allowed = row
            cur.execute(SQL_ITEM_LOCK, (item_id,))
            item = cur.fetchone()
            if item is None:
                raise StorageError(f"없는 물건: {item_id}", not_found=True)
            status, category = item
            if status not in ON_SHELF:
                raise StorageConflict(f"{item_id} 은 '{status}' 상태라 보관함에 넣을 수 없습니다({'·'.join(ON_SHELF)}만)")
            _category_ok({"code": code, "kind": kind, "allowed_categories": list(allowed or [])}, category,
                         override_category)
            cur.execute(SQL_SLOT_LOCK, (slot_id,))
            cur_row = cur.fetchone()
            if cur_row and cur_row[0] != item_id:
                raise StorageConflict(f"{slot_id} 에는 이미 {cur_row[0]} 이 있습니다(먼저 비우기)")
            cur.execute(SQL_MOVE_OUT, (item_id, slot_id))
            if not cur_row:
                cur.execute(SQL_ASSIGN, (slot_id, item_id, by))
                if cur.fetchone() is None:          # 동시에 다른 직원이 먼저 넣음
                    raise StorageConflict(f"{slot_id} 에 방금 다른 물건이 들어갔습니다(새로고침)")
        return {"ok": True, "item_id": item_id, "slot_id": slot_id, "section": code, "slot": str(no),
                "pose_name": pose}

    def release(self, item_id: str | None = None, slot_id: str | None = None) -> dict:
        if (item_id is None) == (slot_id is None):
            raise StorageError("item_id 와 slot_id 중 하나만 보내세요")
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            if slot_id is not None:
                check_slot_id(slot_id)
                cur.execute(SQL_SLOT_ONE, (slot_id,))
                if cur.fetchone() is None:
                    raise StorageError(f"없는 칸: {slot_id}", not_found=True)
                cur.execute(SQL_RELEASE_SLOT, (slot_id,))
                r = cur.fetchone()
                return {"ok": True, "slot_id": slot_id, "item_id": r[0] if r else None}
            check_item_id(item_id)
            cur.execute(SQL_RELEASE_ITEM, (item_id,))
            r = cur.fetchone()
            return {"ok": True, "slot_id": r[0] if r else None, "item_id": item_id}

    def set_pose(self, slot_id: str, pose_name: str | None) -> dict:
        check_slot_id(slot_id)
        pose = check_pose(pose_name)
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_SET_POSE, (pose, slot_id))
            if cur.fetchone() is None:
                raise StorageError(f"없는 칸: {slot_id}", not_found=True)
        return {"ok": True, "slot_id": slot_id, "pose_name": pose}

    def set_bounds(self, section_code: str, bounds_mm: list | None) -> dict:
        import json
        b = _check_bounds(bounds_mm)
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_SET_BOUNDS, (json.dumps(b) if b is not None else None, section_code))
            if cur.fetchone() is None:
                raise StorageError(f"없는 구역: {section_code}", not_found=True)
        return {"ok": True, "section": section_code, "bounds_mm": b}

    def record_check(self, check: dict) -> dict:
        c = parse_check(check)
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_SECTION_EXISTS, (c["section"],))
            if cur.fetchone() is None:
                raise StorageError(f"없는 구역: {c['section']}", not_found=True)
            cur.execute(SQL_CHECK, (c["section"], c["item_id"], c["expected_count"], c["detected_count"], c["status"]))
            cid, at = cur.fetchone()
        return {"id": cid, **c, "at": _iso(at)}

    def recent_checks(self, limit: int = 20) -> list[dict]:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_CHECKS, (max(1, min(int(limit), 100)),))
            return [{"id": i, "section": s, "item_id": it, "expected_count": e, "detected_count": d, "status": st,
                     "at": _iso(at)} for i, s, it, e, d, st, at in cur.fetchall()]
