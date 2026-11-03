"""팀 공통 약속(입·출력 형식) — LF-16.

한줄 설명: 비전·매칭·로봇·DB가 주고받는 값의 모양을 한곳에 정해 두고, 어긋나면 바로 알려 준다.

- 이 파일의 이름·값 목록을 바꾸면 모든 모듈이 영향을 받는다. 바꿀 때는 PR에 이유를 적고 팀원 확인을 받는다.
- 표준 라이브러리만 쓴다(어느 PC에서나 바로 import 되게).
"""
from __future__ import annotations

import re
from datetime import date

UNKNOWN = "확인 불가"          # 사진으로 판단할 수 없을 때(보류)
NONE = "없음"                  # 표시·글자가 없음을 확인했을 때
PII_MASK = "개인정보 가림"      # 카드·신분증의 이름·번호 자리

# 분실물 품목 6종(11/3 핸드크림·보조배터리 정식 추가) + 없음. 물건 ID 앞글자: W 지갑 · U USB · L 립밤 · P 모형폰 · H 핸드크림 · B 보조배터리
CATEGORIES = ["지갑", "USB", "립밤", "모형폰", "핸드크림", "보조배터리", "없음"]
MVP_CATEGORIES = ["지갑"]       # MVP는 지갑 1종, 확장 때 나머지 추가
FEATURE_FIELDS = ["color", "shape", "mark", "visible_text", "material"]
PRIVATE_FIELDS = ["mark", "visible_text"]   # 확인 질문용 비공개 특징(후보 카드에 안 보임)
COLORS = ["검정", "흰색", "회색", "빨강", "파랑", "남색", "초록", "노랑", "갈색", "기타"]
VISIBILITY = ["보임", "안 보임", "해당 없음"]

# 분실인 설명(claim.description) 칸 = 품목 + 접수 특징과 같은 이름(매칭이 칸끼리 바로 비교, 11/3 확정)
DESCRIPTION_FIELDS = ["category", *FEATURE_FIELDS]

# 번호 형식(11/3 확정, docs/design/database.md 6장)
#   접수 번호: 등록기계 문자-날짜-하루 순번 4자리, 예 A-20261103-0001 (시연 물건 A-W01~A-W07 도 허용)
#   찾기 번호: C-날짜-순번, 예 C-20261103-0001
ITEM_ID_PATTERN = r"^[A-Z]-([0-9]{8}-[0-9]{4}|W[0-9]{2})$"
CLAIM_ID_PATTERN = r"^C-[0-9]{8}-[0-9]{4}$"
ITEM_ID_RE = re.compile(ITEM_ID_PATTERN)
CLAIM_ID_RE = re.compile(CLAIM_ID_PATTERN)
MACHINE_LETTERS = {"KIOSK-A": "A", "KIOSK-B": "B", "CENTER": "H"}   # 본센터 직접 접수 = H

# 습득자 연락처(finder_contact) 보관: 인계 완료 뒤 30일이 지나면 지운다(tools/purge_contacts.py)
CONTACT_RETENTION_DAYS = 30

# 물건 상태(기준 문서 3장)
ITEM_STATUS = ["등록기계 보관", "회수 중", "본센터 보관", "확인 중", "승인·수령 예약", "반환 중", "인계 완료", "반환 보류"]

# 메인 AI 결정
DECISION_RETURNED = "returned"        # 바구니까지 전달 완료
DECISION_REJECTED = "rejected"        # 안전 규칙에 막혀 반환하지 않음
DECISION_STAFF = "staff_check"        # 자동으로 정하지 않고 직원 확인으로 넘김
DECISION_STOPPED = "stopped"          # 로봇 동작 중 실패로 정지
DECISIONS = [DECISION_RETURNED, DECISION_REJECTED, DECISION_STAFF, DECISION_STOPPED]

# 매칭 결과 상태
MATCH_OK = "matched"
MATCH_UNCERTAIN = "uncertain"
MATCH_NONE = "none"


def validate_vision_result(d: dict) -> list[str]:
    """비전 결과 JSON 검사. 문제가 없으면 빈 목록."""
    errs: list[str] = []
    if not isinstance(d, dict):
        return ["비전 결과는 dict 여야 합니다"]
    for key in ["category", *FEATURE_FIELDS, "confidence"]:
        if key not in d:
            errs.append(f"{key} 항목이 없습니다")
    cat = d.get("category")
    if cat is not None and cat not in CATEGORIES and cat != UNKNOWN:
        errs.append(f"category 값이 목록에 없습니다: {cat!r}")
    color = d.get("color")
    if color is not None and color not in COLORS and color != UNKNOWN:
        errs.append(f"color 값이 목록에 없습니다: {color!r}")
    conf = d.get("confidence")
    if conf is not None and not (isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0):
        errs.append("confidence 는 0~1 숫자여야 합니다")
    for f in FEATURE_FIELDS:
        v = d.get(f)
        if v is not None and not isinstance(v, str):
            errs.append(f"{f} 는 글자여야 합니다")
    return errs


def validate_detection(d: dict) -> list[str]:
    """탑뷰 사진의 물건 하나: box·center(픽셀) + 비전 결과."""
    errs: list[str] = []
    box, center = d.get("box"), d.get("center")
    if not (isinstance(box, (list, tuple)) and len(box) == 4 and box[0] < box[2] and box[1] < box[3]):
        errs.append("box 는 [x1, y1, x2, y2] (x1<x2, y1<y2) 여야 합니다")
    if not (isinstance(center, (list, tuple)) and len(center) == 2):
        errs.append("center 는 [cx, cy] 여야 합니다")
    errs += [f"features: {e}" for e in validate_vision_result(d.get("features", {}))]
    return errs


def robot_result(ok: bool, reason: str = "") -> dict:
    """로봇 함수의 공통 결과 모양."""
    return {"ok": bool(ok), "reason": "" if ok else (reason or "알 수 없는 실패")}


def make_item_id(machine_id: str, day: date, seq: int) -> str:
    """접수 번호 만들기. 예: make_item_id("KIOSK-A", date(2026, 11, 3), 1) 의 결과는 A-20261103-0001"""
    if machine_id not in MACHINE_LETTERS:
        raise ValueError(f"모르는 등록기계: {machine_id} (허용: {list(MACHINE_LETTERS)})")
    if not 1 <= seq <= 9999:
        raise ValueError("하루 순번은 1~9999")
    return f"{MACHINE_LETTERS[machine_id]}-{day:%Y%m%d}-{seq:04d}"


def validate_description(desc: dict) -> list[str]:
    """분실인 설명 JSON 의 칸 이름 검사(DB CHECK 와 같은 규칙)."""
    return [f"모르는 칸: {k} (허용: {DESCRIPTION_FIELDS})" for k in desc if k not in DESCRIPTION_FIELDS]


def public_card(features: dict) -> dict:
    """후보 카드에 보여도 되는 값만 남긴다(비공개 특징 제거)."""
    return {k: v for k, v in features.items() if k not in PRIVATE_FIELDS}
