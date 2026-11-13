"""모델/네트워크와 분리된 칸 배정 및 비교 규칙."""
from __future__ import annotations

import hashlib
import json
import math

SLOTS = tuple(f"R{column}-{row}" for column in range(1, 5) for row in (1, 2))
ON_SHELF = {"본센터 보관", "확인 중", "승인·수령 예약"}
CATEGORIES = {"phone": "휴대폰", "power_bank": "보조배터리", "hand_cream": "핸드크림",
              "lip_balm": "립밤", "wallet": "카드지갑", "usb": "USB", "목업폰": "휴대폰", "모형폰": "휴대폰"}


def layout_rows(payload):
    layout = payload.get("layout", payload)
    return {slot["slot_id"]: {"item": slot.get("item"), "allowed_categories": section.get("allowed_categories", [])}
            for section in layout.get("sections", []) for slot in section.get("slots", [])
            if slot.get("slot_id") in SLOTS}


def layout_digest(payload):
    # Ignore export timestamps/summary counters, compare only the eight operational assignments.
    return hashlib.sha256(json.dumps(layout_rows(payload), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_regions(config):
    width, height = config["image_size_px"]
    if width <= 0 or height <= 0 or set(config["regions"]) != set(SLOTS):
        raise ValueError("현재 해상도와 R1-1~R4-2의 8개 영역이 필요합니다.")
    boxes = config["regions"]
    for name, box in boxes.items():
        if len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
            raise ValueError(f"{name}: 유효한 좌표 4개가 필요합니다.")
        x1, y1, x2, y2 = box
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError(f"{name}: 영역이 영상 밖이거나 뒤집혀 있습니다.")
    for i, name in enumerate(SLOTS):
        for other in SLOTS[i + 1:]:
            if intersection(boxes[name], boxes[other]) > 0:
                raise ValueError(f"영역 중복: {name}, {other}")
    return config


def intersection(a, b):
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def assign_objects(objects, config):
    assigned = {name: [] for name in SLOTS}
    uncertain = {name: [] for name in SLOTS}
    outside = []
    margin = config.get("boundary_margin_px", 10)
    for obj in objects:
        if obj.get("quality") == "rejected":
            continue
        box = obj["bbox_px"]
        cx, cy = obj["center_px"]
        area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
        overlap = {name: intersection(box, region) / area for name, region in config["regions"].items()}
        centers = [name for name, (x1, y1, x2, y2) in config["regions"].items()
                   if x1 <= cx < x2 and y1 <= cy < y2]
        name = centers[0] if len(centers) == 1 else None
        if name:
            x1, y1, x2, y2 = config["regions"][name]
            ambiguous = min(cx-x1, x2-cx, cy-y1, y2-cy) < margin or overlap[name] < .55
            ambiguous |= any(ratio > .30 for other, ratio in overlap.items() if other != name)
        else:
            ambiguous = True
        if obj.get("quality") != "accepted" or ambiguous:
            touched = [key for key, ratio in overlap.items() if ratio > .08 or key == name]
            for key in touched:
                uncertain[key].append(obj)
            if not touched:
                outside.append(obj)
        else:
            assigned[name].append(obj)
    return assigned, uncertain, outside


def compare(observation, before, after, config, *, unavailable=None, busy=False):
    validate_regions(config)
    assigned, uncertain, outside = assign_objects(observation.get("objects", []), config)
    rows = layout_rows(after) if after else {}
    changed = before is not None and after is not None and layout_digest(before) != layout_digest(after)
    reason = unavailable
    if list(observation.get("captured_size", [])) != list(config["image_size_px"]):
        reason = "해상도 변경 — 영역을 다시 지정하세요."
    if before is None or after is None:
        reason = reason or "DB 연결 안 됨"
    if changed:
        reason = "분석 중 DB 배정 변경 — 다음 프레임에서 재검증"
    result = []
    for name in SLOTS:
        row = rows.get(name)
        item = row.get("item") if row else None
        status = item.get("status") if item else None
        expected = (1 if status in ON_SHELF else None) if item else (0 if row else None)
        found = assigned[name]
        seen = len(found)
        expected_category = CATEGORIES.get(item.get("category"), item.get("category")) if item else None
        categories = [CATEGORIES.get(obj.get("category"), obj.get("category")) for obj in found]
        if reason or row is None:
            state, detail = "unavailable", reason or "DB에 해당 칸 없음"
        elif busy or expected is None:
            state, detail = "transition", "로봇 동작/반환 전환 중 또는 상태 미확인"
        elif uncertain[name]:
            state, detail = "ambiguous", "경계/검출 품질 검토 필요"
        elif seen > 1:
            state, detail = "multiple", "한 칸에 여러 검출 — 중복 또는 다중 적재 검토"
        elif expected == 1 and seen == 0:
            state, detail = "missing_candidate", "DB 1개 / 실물 미검출 후보"
        elif expected == 0 and seen:
            state, detail = "unexpected_candidate", "DB 빈 칸 / 실물 검출"
        elif expected == 1 and categories != [expected_category]:
            state, detail = "category_mismatch", "검출 품목과 DB 품목 다름"
        else:
            state, detail = "count_match", "개수·품목 일치 / 개체 ID 미확인" if seen else "빈 칸 일치"
        result.append({"slot_id": name, "state": state, "detail": detail, "expected_count": expected,
                       "detected_count": seen, "review_count": len(uncertain[name]), "categories": categories,
                       "item_id": item.get("item_id") if item else None, "db_status": status,
                       "expected_category": expected_category, "identity_verified": False})
    return {"slots": result, "outside_objects": outside, "db_changed": changed, "unavailable": reason,
            "identity_verified": False}
