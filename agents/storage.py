"""본센터 보관함 정답지 (LF-8 · 11/6 변재원)

한줄 설명: "물건 X 는 보관함 몇 행 몇 번 칸에 있고, 로봇팔은 어느 저장 자세(pose)로 가야 하는가"를 기억하고,
비전(김건태) run_storage_check.py 가 읽는 storage JSON 으로 내보낸다.

흐름: 등록기계 → 본센터 도착(본센터 보관) → 직원이 칸에 넣고 assign → YOLO 가 그 행만 잘라 개수 확인 → 로봇이 저장 자세로 집기
      → 인계 완료가 되면 칸이 자동으로 빈다(DB 트리거, 메모리 저장소는 읽을 때 거름). 인계 대기 동안은 칸 예약 유지(11/6 교차 검증)

배치(center/migrations/007 + 014 + 015 + 016): 4행 × 2칸 = 8칸 + 인계 구역 H-1(제출보관함 20×20cm) + 직원 보관 선반 S(로봇 안 씀)
- 11/9 사용자 결정(014): R1 = 휴대폰 전용(폰을 사선으로 둬서 간격이 넓음) · R2~R4 = 휴대폰 밖 5종(행마다 품목 제한 없음)
- 11/9 사용자 결정(015): 립밤을 운영 품목에서 빼고 열마다 품목 하나
- 11/9 사용자 결정(016): 품목 4종 고정(목업폰·보조배터리·핸드크림·카드지갑) — R1 휴대폰('/' 45도) · R2 카드지갑 · R3 보조배터리 · R4 핸드크림
- 11/10 사용자 결정(018): 열 순서를 다시 정함 — 왼쪽부터 R1 휴대폰 · R2 보조배터리 · R3 핸드크림 · R4 카드지갑(칸 위치·로봇 자세는 그대로, 품목만)
- 인계 구역 H-1(제출보관함)은 보관판 위쪽(로봇 반대쪽) 긴 변 가운데에 붙음
- 직원 보관 선반 S: 맞는 빈 칸이 없을 때 넘치는 물건 자리. 로봇이 집지 않고 비전 내보내기에도 넣지 않는다. 칸은 필요할 때 S-1, S-2 … 로 늘린다
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

from agents.contracts import ITEM_ID_RE, MVP_CATEGORIES, category_label

# 김건태 run_storage_check.ON_SHELF 와 같음: 이 상태일 때만 보관함 위에 있다고 본다
ON_SHELF = ("본센터 보관", "확인 중", "승인·수령 예약")
ARRIVING = ("등록기계 보관", "회수 중")   # 11/6 본센터 도착 처리(place)로 칸에 넣으면서 '본센터 보관'으로 바꿀 수 있는 상태
RELEASE_STATUSES = ("인계 완료",)   # 11/6: 인계 대기 중에는 칸 예약 유지(교차 검증이 틀리면 원래 칸으로), 011 마이그레이션
CHECK_STATUSES = ("count_match", "count_mismatch", "verification_unavailable", "resolution_mismatch",
                  "invalid_calibration", "section_out_of_frame", "match_held")
POSE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SLOT_RE = re.compile(r"^[A-Z][0-9]?-[0-9]{1,2}$")

# (구역, 이름, 종류, 허용 품목, 칸 수, 칸 메모) — 007 시작값 + 008·009·014·015·016 을 차례로 적용한 결과와 같게(tests/test_storage.py)
# 종류: shelf = 로봇이 집는 보관 칸 · handover = 제출보관함 · staff = 직원 보관 선반(로봇 안 씀, 칸 수는 필요할 때 늘림 → 시작 0)
PHONE_ONLY = ["모형폰"]                                            # 품목 값은 '모형폰', 화면 이름은 '휴대폰'(contracts.category_label)
NOT_PHONE = [c for c in MVP_CATEGORIES if c not in PHONE_ONLY]    # 휴대폰 밖 운영 품목(11/9: 지갑·핸드크림·보조배터리)
# 11/9 사용자 결정(015): 열(탑뷰 왼쪽부터 R1~R4) 하나 = 품목 하나. 각 열 2칸(-1 먼 칸=탑뷰 위, -2 로봇 가까운 칸 — 11/11 실물 확인)
#   R1 휴대폰(45도 사선) · R2 보조배터리 · R3 핸드크림 · R4 지갑(보이는 이름 카드지갑) — 11/10 018 에서 순서를 다시 정함(016: 품목 4종 고정)
#   운영 품목(contracts.ACTIVE_CATEGORIES)에서 빠진 품목은 열에서도 자동으로 빠진다. 단 DB 는 마이그레이션으로만 바뀌므로
#   품목을 빼면 새 마이그레이션도 함께 만든다(LAYOUT 과 DB 가 다르면 tests/test_storage.py 가 실패해서 알려 줌)
#   11/10 사용자 결정(018): 왼쪽부터 휴대폰 · 보조배터리 · 핸드크림 · 카드지갑 (R2·R3·R4 를 실물 배치대로 다시 정함)
ROW_CATEGORIES = {"R1": ["모형폰"], "R2": ["보조배터리"], "R3": ["핸드크림"], "R4": ["지갑"]}
# 칸 이름표에 쓰는 실물 이름(품목 값·화면 이름과 다를 때만). 016: 지갑 열은 실물대로 '카드지갑'
ROW_NAME = {"지갑": "카드지갑"}
# R1 메모: 비전(YOLO·Qwen)이 가로로 놓인 휴대폰을 잘 못 알아봐서 45도 사선으로 둔다.
#   방향 = 탑뷰 화면에서 '/' — 휴대폰 상단(카메라)이 오른쪽 위, 케이블 꽂는 쪽(단자)이 왼쪽 아래(11/9 09:51 사용자 결정 변경, docs/design/storage_slots.md 2장)
PHONE_NOTE = "45도 사선·상단 오른쪽 위"


def _row_categories(code: str) -> list[str]:
    """그 열이 받는 운영 품목(운영 품목에서 빠진 것은 뺀다)"""
    return [c for c in ROW_CATEGORIES[code] if c in MVP_CATEGORIES]


def _row_label(code: str) -> str:
    cats = _row_categories(code)
    if cats == PHONE_ONLY:
        return f"{code} {category_label(PHONE_ONLY[0])} 전용"
    return f"{code} " + "·".join(ROW_NAME.get(c, category_label(c)) for c in cats)


LAYOUT = [
    ("R1", _row_label("R1"), "shelf", _row_categories("R1"), 2, PHONE_NOTE),
    ("R2", _row_label("R2"), "shelf", _row_categories("R2"), 2, None),
    ("R3", _row_label("R3"), "shelf", _row_categories("R3"), 2, None),
    ("R4", _row_label("R4"), "shelf", _row_categories("R4"), 2, None),
    ("H", "인계 구역(제출보관함)", "handover", [], 1, "20×20cm·보관판 위쪽 가운데"),
    ("S", "직원 보관 선반", "staff", [], 0, None),
]
STAFF_KIND = "staff"
SHELF_SECTION = "S"
SHELF_NOTE = "직원 보관(로봇 안 씀)"
SHELF_MAX = 99                     # 칸 번호 형식(S-1 ~ S-99) 한계. 실제로는 넘칠 일 없음
SHELF_FROM = ("본센터 보관",) + ("등록기계 보관", "회수 중")   # 선반으로 옮길 수 있는 상태(대기 물건은 직원이 가져와 바로 선반에)

# 11/6 김건태 확정(디스코드 일반 채널): 칸 ↔ 로봇 저장 자세(poses.json, Studio normalized 관절값) — 013 마이그레이션과 같음
# 각 행 1(먼 칸, 탑뷰 위) = pose_1·3·5·7, 2(로봇팔 가까운 칸) = pose_2·4·6·8 (11/11 실물 확인). H-1 은 배출구에 내려놓는 자세 close
SLOT_POSES = {"R1-1": "pose_1", "R1-2": "pose_2", "R2-1": "pose_3", "R2-2": "pose_4",
              "R3-1": "pose_5", "R3-2": "pose_6", "R4-1": "pose_7", "R4-2": "pose_8", "H-1": "close"}
# 집은 뒤 배출구(제출보관함)까지: 원복 1단계 → close(배출구 위, 집게 닫힘) → open(집게 열어 놓기) → 원복 1단계 → home
OUTLET_SEQUENCE = ("outlet_return_1", "close", "open", "outlet_return_1", "home")
# 11/9 사용자 번호(로봇팔 - DB 연결 문서 docs/contracts/robot_db_target.md): 먼 줄(탑뷰 위) 1·3·5·7, 로봇 가까운 줄 2·4·6·8 (11/11 실물 확인: 왼쪽 위가 1)
#   탑뷰에서 왼쪽 열(R1)부터 오른쪽 열(R4). 번호 N = 저장 자세 pose_N 의 N(013 마이그레이션·SLOT_POSES 와 같음)
SLOT_NUMBERS = {"R1-1": 1, "R1-2": 2, "R2-1": 3, "R2-2": 4, "R3-1": 5, "R3-2": 6, "R4-1": 7, "R4-2": 8}


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
    def place(self, item_id: str, slot_id: str, override_category: bool = False) -> dict: ...
    def unplaced(self, limit: int = 50) -> list[dict]: ...
    def move_to_shelf(self, item_id: str, by: str = "staff") -> dict: ...
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
        if s["kind"] == STAFF_KIND:          # 11/9 직원 보관 선반은 보관판 밖(탑뷰·로봇 대상 아님) → 비전에 넘기지 않음
            continue
        entry = {"label": s["label"], "kind": s["kind"],
                 "slots": {str(slot["slot_no"]): slot["pose_name"] for slot in s["slots"]}}
        if s.get("bounds_mm"):
            entry["bounds_mm"] = list(s["bounds_mm"])
        out_sections[s["code"]] = entry
    inventory = {}
    for a in sorted(assignments, key=lambda a: a["slot_id"]):
        if a["status"] not in ON_SHELF or a["section"] not in out_sections:
            continue
        inventory[a["item_id"]] = {"section": a["section"], "slot": str(a["slot_no"])}
        if not out_sections[a["section"]]["slots"].get(str(a["slot_no"])):
            warnings.append(f"{a['slot_id']}: 물건 {a['item_id']} 이 있지만 저장 자세가 비어 있음(로봇 티칭 필요)")
    return {"sections": out_sections, "inventory": inventory, "warnings": warnings, "exported_at": _now()}


def _category_ok(section: dict, category: str | None, override: bool) -> None:
    allowed = section["allowed_categories"]
    if section["kind"] == "handover":
        raise StorageError("인계 구역(H)은 로봇이 바구니로 옮길 때만 씁니다. 보관 칸(R1~R4)을 고르세요")
    if section["kind"] == STAFF_KIND:
        return                               # 직원 보관 선반: 품목 제한 없음(로봇이 집지 않음)
    # category None = 품목 정보가 없는 시연 부품(evaluation/test_cases.json) → 막지 않음. DB 의 '확인 불가'는 막음
    if allowed and category is not None and category not in allowed and not override:
        raise StorageError(f"{section['code']} 행은 {'·'.join(category_label(a) for a in allowed)} 자리입니다(이 물건: {category_label(category)}). "
                           "그래도 넣으려면 override_category: true")


def _fits(section: dict, category: str) -> bool:
    return category in section["allowed_categories"] or not section["allowed_categories"]


def _near_first(pairs: list) -> list:
    """1번 칸(먼 줄)부터, 같은 번호면 행 순서(R1 → R4). [(구역, 칸)] 그대로 정렬"""
    return sorted(pairs, key=lambda p: (p[1]["slot_no"], p[0].get("sort", 0), p[0]["code"]))


def recommend_slot(layout: dict, category: str | None) -> dict | None:
    """품목에 맞는 빈 칸 추천(11/9 규칙): 그 품목을 받는 행(또는 품목 제한 없는 행)의 빈 칸 중 1번 칸(먼 줄)부터.
    11/9: 품목이 다른 열(018: R1 휴대폰 · R2 보조배터리 · R3 핸드크림 · R4 카드지갑)은 섞지 않는다 → 맞는 빈 칸이 없으면 None(직원 보관 선반 추천은 shelf_or_slot).
    품목을 모르면(None·확인 불가) 추천하지 않는다(직원이 사진을 보고 고름)"""
    if not category or category == "확인 불가":
        return None
    shelves = [s for s in layout["sections"] if s["kind"] == "shelf"]
    free = [(s, slot) for s in shelves for slot in s["slots"] if slot.get("item") is None]
    for want in (lambda s: category in s["allowed_categories"], lambda s: not s["allowed_categories"]):
        hit = _near_first([(s, slot) for s, slot in free if want(s)])
        if hit:
            s, slot = hit[0]
            return {"slot_id": slot["slot_id"], "section": s["code"], "label": s["label"],
                    "pose_name": slot.get("pose_name"), "other_row": False}
    return None


def shelf_suggestion() -> dict:
    """맞는 빈 칸이 없을 때 도착 화면이 보여 줄 추천: 직원 보관 선반(칸 번호는 옮길 때 정해짐)"""
    return {"slot_id": None, "section": SHELF_SECTION, "label": "직원 보관 선반", "pose_name": None,
            "other_row": False, "shelf": True}


def _number_row(slot_id: str) -> dict:
    n = SLOT_NUMBERS.get(slot_id)
    return {"number": n, "row": None if n is None else ("far" if n % 2 else "near")}


def robot_target(layout: dict, item_id: str) -> dict:
    """물건 번호 → 로봇팔이 갈 곳(11/9, 탑뷰 없이 DB 만으로). 로봇을 움직이지 않고 읽기만 한다.

    ok=True  : {"slot_id", "number"(1~8), "row"(far=홀수·탑뷰 위 / near=짝수·로봇 쪽), "column"(R1~R4), "pose_name", "bounds_mm", "outlet_sequence"}
    ok=False : code = no_slot(칸 기록 없음) · staff_shelf(직원 보관 선반, 로봇 안 씀) · not_robot_slot(인계 구역 등)
               · no_pose(칸에 저장 자세 이름 없음 — 티칭·보관함 화면에서 연결 필요)
    pose_expected: 번호대로라면 있어야 할 이름(pose_N). 실제 pose_name 과 다르면 warnings 에 남긴다(화면에서 바꾼 값일 수 있음)"""
    for sec in layout.get("sections", []):
        for slot in sec.get("slots", []):
            if not slot.get("item") or slot["item"].get("item_id") != item_id:
                continue
            base = {"item_id": item_id, "slot_id": slot["slot_id"], "column": sec["code"],
                    "category": slot["item"].get("category"), **_number_row(slot["slot_id"])}
            if sec.get("kind") == STAFF_KIND:
                return {"ok": False, "code": "staff_shelf", "reason": "직원 보관 선반 물건 — 로봇을 쓰지 않고 직원이 건넴", **base}
            if sec.get("kind") != "shelf" or base["number"] is None:
                return {"ok": False, "code": "not_robot_slot", "reason": f"{slot['slot_id']} 은 로봇이 집는 보관 칸(1~8)이 아님", **base}
            pose = slot.get("pose_name")
            expected = f"pose_{base['number']}"
            if not pose:
                return {"ok": False, "code": "no_pose", "pose_expected": expected,
                        "reason": f"{slot['slot_id']}(번호 {base['number']})에 저장 자세 이름이 없음 — 보관함 화면에서 {expected} 연결", **base}
            warnings = [] if pose == expected else [f"자세 이름 {pose} 이 번호대로의 {expected} 와 다름 — 로봇 PC poses.json 이름과 같은지 확인"]
            return {"ok": True, "pose_name": pose, "pose_expected": expected, "bounds_mm": sec.get("bounds_mm"),
                    "outlet_sequence": list(OUTLET_SEQUENCE), "warnings": warnings, **base}
    return {"ok": False, "code": "no_slot", "item_id": item_id, "number": None, "row": None,
            "reason": f"물건 {item_id} 의 보관 칸 기록 없음 — 보관함 화면에서 칸에 넣은 기록부터"}


def robot_targets(layout: dict) -> list[dict]:
    """번호 1~8 칸 전체 표(로봇 PC 가 한 번에 읽어 두는 용도): 번호·칸·열·줄·자세 이름·들어 있는 물건 번호·품목"""
    out = []
    for sec in layout.get("sections", []):
        if sec.get("kind") != "shelf":
            continue
        for slot in sec.get("slots", []):
            nr = _number_row(slot["slot_id"])
            if nr["number"] is None:
                continue
            item = slot.get("item") or {}
            out.append({"slot_id": slot["slot_id"], "column": sec["code"], "label": sec.get("label"), **nr,
                        "pose_name": slot.get("pose_name"), "pose_expected": f"pose_{nr['number']}",
                        "item_id": item.get("item_id"), "category": item.get("category"),
                        "bounds_mm": sec.get("bounds_mm")})
    return sorted(out, key=lambda r: r["number"])


def slot_groups(layout: dict) -> list[dict]:
    """보관 칸 묶음별 사용 현황(11/9): 받는 품목이 같은 행끼리 한 묶음 — 016 기준 휴대폰(R1)·카드지갑(R2)·보조배터리(R3)·핸드크림(R4) 각 2칸.
    운영하지 않는 품목(립밤)은 받는 묶음이 없다 → group_of 가 None(칸 대기에 세지 않고 직원 보관 선반으로).
    [{"key", "label", "rows", "categories", "used", "total"}] (key: phone | other | 품목 이름을 이은 글)"""
    groups: dict[tuple, dict] = {}
    for s in layout["sections"]:
        if s["kind"] != "shelf":
            continue
        allowed = tuple(s["allowed_categories"])
        g = groups.get(allowed)
        if g is None:
            if list(allowed) == PHONE_ONLY:
                key, label = "phone", category_label(PHONE_ONLY[0])
            elif not allowed:
                key, label = "any", "제한 없음"
            elif sorted(allowed) == sorted(NOT_PHONE):
                key, label = "other", "그 밖"
            else:
                key, label = "·".join(allowed), "·".join(category_label(c) for c in allowed)
            g = groups[allowed] = {"key": key, "label": label, "rows": [], "categories": list(allowed), "used": 0, "total": 0}
        g["rows"].append(s["code"])
        for slot in s["slots"]:
            g["total"] += 1
            g["used"] += slot.get("item") is not None
    return list(groups.values())


def group_of(groups: list[dict], category: str | None) -> dict | None:
    """그 품목이 들어갈 묶음(받는 행 → 제한 없는 행). 품목을 모르면 None"""
    if not category or category == "확인 불가":
        return None
    return (next((g for g in groups if category in g["categories"]), None)
            or next((g for g in groups if not g["categories"]), None))


def shelf_items(layout: dict) -> list[dict]:
    """직원 보관 선반에 있는 물건(번호·칸·품목·상태만)"""
    return [{"slot_id": slot["slot_id"], **slot["item"]} for s in layout["sections"] if s["kind"] == STAFF_KIND
            for slot in s["slots"] if slot.get("item")]


class MemoryStorageStore:
    """프로그램이 켜져 있는 동안만 기억(시연·시험용). item_lookup(item_id) → {"status", "category"} | None"""

    def __init__(self, item_lookup: Callable[[str], dict | None] | None = None, layout=None,
                 item_source: Callable[[], list[dict]] | None = None,
                 status_setter: Callable[[str, str], bool] | None = None,
                 poses: dict[str, str] | None = None):
        self._lock = threading.Lock()
        self._lookup = item_lookup
        self._source = item_source        # 11/6 도착 목록용: [{"item_id","status","category",...}]
        self._set_status = status_setter  # 11/6 도착 처리: (item_id, status) → 성공 여부
        self._sections: list[dict] = []
        for order, (code, label, kind, allowed, n, note) in enumerate(layout or LAYOUT, start=1):
            self._sections.append({"code": code, "label": label, "kind": kind, "allowed_categories": list(allowed),
                                   "bounds_mm": None, "sort": order,
                                   "slots": [{"slot_id": f"{code}-{i}", "slot_no": i,
                                              "pose_name": (poses or {}).get(f"{code}-{i}"), "note": note}
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

    def assign(self, item_id: str, slot_id: str, override_category: bool = False, by: str = "staff",
               arrive: bool = False) -> dict:
        check_item_id(item_id)
        check_slot_id(slot_id)
        with self._lock:
            self._rows()                          # 바구니로 나간 물건의 칸을 먼저 비움(트리거 대신)
            section, slot = self._slot(slot_id)
            item = self._item(item_id)
            arriving = arrive and item.get("status") in ARRIVING
            if not arriving and item.get("status") not in ON_SHELF:
                raise StorageConflict(f"{item_id} 은 '{item.get('status')}' 상태라 보관함에 넣을 수 없습니다"
                                      f"({'·'.join(ON_SHELF)}만)")
            _category_ok(section, item.get("category"), override_category)
            current = self._assign.get(slot_id)
            if current and current["item_id"] != item_id:
                raise StorageConflict(f"{slot_id} 에는 이미 {current['item_id']} 이 있습니다(먼저 비우기)")
            if arriving:                           # 검사를 다 통과한 뒤에만 상태를 바꾼다
                if self._set_status is None or not self._set_status(item_id, "본센터 보관"):
                    raise StorageConflict(f"{item_id} 상태를 '본센터 보관'으로 바꾸지 못함 — 칸에 넣지 않음")
            for sid, a in list(self._assign.items()):
                if a["item_id"] == item_id and sid != slot_id:
                    del self._assign[sid]      # 다른 칸에서 옮겨 옴
            self._assign[slot_id] = {"item_id": item_id, "assigned_at": _now(), "assigned_by": by}
            return {"ok": True, "item_id": item_id, "slot_id": slot_id, "section": section["code"],
                    "slot": str(slot["slot_no"]), "pose_name": slot["pose_name"]}

    def place(self, item_id: str, slot_id: str, override_category: bool = False) -> dict:
        """본센터 도착 처리(11/6): 직원이 칸에 넣음 → (등록기계 보관·회수 중이면) 본센터 보관 + 칸 기록"""
        return {**self.assign(item_id, slot_id, override_category, by="staff", arrive=True), "status": "본센터 보관"}

    def move_to_shelf(self, item_id: str, by: str = "staff") -> dict:
        """11/9 직원 보관 선반으로(칸이 꽉 찼을 때): 보관 칸의 물건이나 칸 대기 물건 → S-n(빈 선반 자리, 없으면 새로).
        등록기계 보관·회수 중이던 물건은 직원이 가져와 바로 선반에 둔 것 → 본센터 보관"""
        check_item_id(item_id)
        with self._lock:
            self._rows()
            item = self._item(item_id)
            status = item.get("status")
            if status not in SHELF_FROM:
                raise StorageConflict(f"{item_id} 은 '{status}' 상태라 선반으로 옮길 수 없습니다({'·'.join(SHELF_FROM)}만)")
            sec = next((s for s in self._sections if s["kind"] == STAFF_KIND), None)
            if sec is None:
                raise StorageError("직원 보관 선반(구역 S)이 없습니다(014 마이그레이션)", not_found=True)
            here = next((sid for sid, a in self._assign.items() if a["item_id"] == item_id), None)
            if here and here.startswith(sec["code"] + "-"):
                return {"ok": True, "item_id": item_id, "slot_id": here, "section": sec["code"], "from": here,
                        "status": status}
            slot = next((sl for sl in sec["slots"] if sl["slot_id"] not in self._assign), None)
            if slot is None:
                n = len(sec["slots"]) + 1
                if n > SHELF_MAX:
                    raise StorageConflict(f"직원 보관 선반 자리 번호가 {SHELF_MAX}개를 넘음 — 선반 정리 필요")
                slot = {"slot_id": f"{sec['code']}-{n}", "slot_no": n, "pose_name": None, "note": SHELF_NOTE}
                sec["slots"].append(slot)
            if status in ARRIVING:
                if self._set_status is None or not self._set_status(item_id, "본센터 보관"):
                    raise StorageConflict(f"{item_id} 상태를 '본센터 보관'으로 바꾸지 못함 — 선반에 기록하지 않음")
            if here:
                del self._assign[here]
            self._assign[slot["slot_id"]] = {"item_id": item_id, "assigned_at": _now(), "assigned_by": by}
            return {"ok": True, "item_id": item_id, "slot_id": slot["slot_id"], "section": sec["code"], "from": here,
                    "status": "본센터 보관"}

    def unplaced(self, limit: int = 50) -> list[dict]:
        """칸이 정해지지 않은 물건(등록기계 보관·회수 중·본센터 보관), 오래된 접수부터"""
        if self._source is None:
            return []
        with self._lock:
            placed = {a["item_id"] for a in self._assign.values()}
        rows = [r for r in self._source() if r.get("status") in ARRIVING + ("본센터 보관",) and r["item_id"] not in placed]
        rows.sort(key=lambda r: (str(r.get("received_at") or ""), r["item_id"]))
        return rows[:max(1, min(int(limit), 200))]

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
    total = used = missing_pose = staff = 0
    for s in sections:
        s.pop("sort", None)
        for slot in s["slots"]:
            r = rows.get(slot["slot_id"])
            slot["item"] = ({"item_id": r["item_id"], "status": r["status"], "category": r["category"],
                             "assigned_at": r["assigned_at"]} if r else None)
            if s["kind"] == "shelf":
                total += 1
                used += r is not None
                missing_pose += slot["pose_name"] is None
            elif s["kind"] == STAFF_KIND:
                staff += r is not None
    view = {"sections": sections}
    # 11/9 groups = 묶음별 사용(016: 열마다 x/2 — 휴대폰·카드지갑·보조배터리·핸드크림), staff_shelf = 직원 보관 선반 물건 수
    return {**view, "summary": {"shelf_slots": total, "used": used, "free": total - used,
                                "slots_without_pose": missing_pose, "staff_shelf": staff, "groups": slot_groups(view)}}


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
SQL_ARRIVE = "UPDATE item SET status = '본센터 보관', updated_at = now() WHERE item_id = %s"
SQL_ARRIVE_LOG = ("INSERT INTO item_status_log (item_id, from_status, to_status, changed_by) "
                  "VALUES (%s, %s, '본센터 보관', 'staff')")
# 11/9 직원 보관 선반: 빈 선반 자리(가장 작은 번호) → 없으면 다음 번호 자리를 새로 만든다(동시에 두 직원이 옮기면 하나는 다시 시도)
SQL_SHELF_FREE = ("SELECT s.slot_id FROM storage_slot s WHERE s.section_code = %s AND NOT EXISTS "
                  "(SELECT 1 FROM storage_assignment a WHERE a.slot_id = s.slot_id) ORDER BY s.slot_no LIMIT 1 "
                  "FOR UPDATE OF s SKIP LOCKED")
SQL_SHELF_NEW = ("INSERT INTO storage_slot (slot_id, section_code, slot_no, note) "
                 "SELECT %s || '-' || n, %s, n, %s FROM (SELECT COALESCE(MAX(slot_no), 0) + 1 AS n FROM storage_slot "
                 "WHERE section_code = %s) x WHERE n <= %s ON CONFLICT DO NOTHING RETURNING slot_id")
SQL_ITEM_SLOT = "SELECT slot_id FROM storage_assignment WHERE item_id = %s"
SQL_UNPLACED = ("SELECT i.item_id, i.status, i.category, i.machine_id, i.received_at, i.features FROM item i "
                "WHERE i.status = ANY(%s) AND NOT EXISTS (SELECT 1 FROM storage_assignment a WHERE a.item_id = i.item_id) "
                "ORDER BY i.received_at, i.item_id LIMIT %s")


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

    def assign(self, item_id: str, slot_id: str, override_category: bool = False, by: str = "staff",
               arrive: bool = False) -> dict:
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
            arriving = arrive and status in ARRIVING
            if not arriving and status not in ON_SHELF:
                raise StorageConflict(f"{item_id} 은 '{status}' 상태라 보관함에 넣을 수 없습니다({'·'.join(ON_SHELF)}만)")
            _category_ok({"code": code, "kind": kind, "allowed_categories": list(allowed or [])}, category,
                         override_category)
            cur.execute(SQL_SLOT_LOCK, (slot_id,))
            cur_row = cur.fetchone()
            if cur_row and cur_row[0] != item_id:
                raise StorageConflict(f"{slot_id} 에는 이미 {cur_row[0]} 이 있습니다(먼저 비우기)")
            if arriving:                           # 같은 거래 안에서 상태·기록·칸을 함께(하나라도 실패하면 모두 취소)
                cur.execute(SQL_ARRIVE, (item_id,))
                cur.execute(SQL_ARRIVE_LOG, (item_id, status))
            cur.execute(SQL_MOVE_OUT, (item_id, slot_id))
            if not cur_row:
                cur.execute(SQL_ASSIGN, (slot_id, item_id, by))
                if cur.fetchone() is None:          # 동시에 다른 직원이 먼저 넣음
                    raise StorageConflict(f"{slot_id} 에 방금 다른 물건이 들어갔습니다(새로고침)")
        return {"ok": True, "item_id": item_id, "slot_id": slot_id, "section": code, "slot": str(no),
                "pose_name": pose}

    def place(self, item_id: str, slot_id: str, override_category: bool = False) -> dict:
        """본센터 도착 처리(11/6): 등록기계 보관·회수 중 → 본센터 보관 + 칸 기록을 거래 하나로"""
        return {**self.assign(item_id, slot_id, override_category, by="staff", arrive=True), "status": "본센터 보관"}

    def move_to_shelf(self, item_id: str, by: str = "staff") -> dict:
        """11/9 직원 보관 선반으로 — 상태(대기 물건이면 본센터 보관)·기록·칸을 거래 하나로"""
        check_item_id(item_id)
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_ITEM_LOCK, (item_id,))
            item = cur.fetchone()
            if item is None:
                raise StorageError(f"없는 물건: {item_id}", not_found=True)
            status = item[0]
            if status not in SHELF_FROM:
                raise StorageConflict(f"{item_id} 은 '{status}' 상태라 선반으로 옮길 수 없습니다({'·'.join(SHELF_FROM)}만)")
            cur.execute(SQL_SECTION_EXISTS, (SHELF_SECTION,))
            if cur.fetchone() is None:
                raise StorageError("직원 보관 선반(구역 S)이 없습니다(014 마이그레이션 적용 필요)", not_found=True)
            cur.execute(SQL_ITEM_SLOT, (item_id,))
            here = (cur.fetchone() or [None])[0]
            if here and here.startswith(SHELF_SECTION + "-"):
                return {"ok": True, "item_id": item_id, "slot_id": here, "section": SHELF_SECTION, "from": here,
                        "status": status}
            cur.execute(SQL_SHELF_FREE, (SHELF_SECTION,))
            row = cur.fetchone()
            if row is None:
                cur.execute(SQL_SHELF_NEW, (SHELF_SECTION, SHELF_SECTION, SHELF_NOTE, SHELF_SECTION, SHELF_MAX))
                row = cur.fetchone()
                if row is None:
                    raise StorageConflict("선반 자리를 만들지 못함(동시에 옮기는 중이거나 99개 넘음) — 새로고침 후 다시")
            slot_id = row[0]
            if status in ARRIVING:
                cur.execute(SQL_ARRIVE, (item_id,))
                cur.execute(SQL_ARRIVE_LOG, (item_id, status))
            cur.execute(SQL_MOVE_OUT, (item_id, slot_id))
            cur.execute(SQL_ASSIGN, (slot_id, item_id, "staff" if by not in ("staff", "tower", "system") else by))
            if cur.fetchone() is None:
                raise StorageConflict(f"{slot_id} 에 방금 다른 물건이 들어갔습니다(새로고침)")
        return {"ok": True, "item_id": item_id, "slot_id": slot_id, "section": SHELF_SECTION, "from": here,
                "status": "본센터 보관"}

    def unplaced(self, limit: int = 50) -> list[dict]:
        with self._connect(self._dsn) as conn, conn.cursor() as cur:
            cur.execute(SQL_UNPLACED, (list(ARRIVING) + ["본센터 보관"], max(1, min(int(limit), 200))))
            return [{"item_id": i, "status": st, "category": cat, "machine_id": m, "received_at": _iso(at),
                     "features": f or {}} for i, st, cat, m, at, f in cur.fetchall()]

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
