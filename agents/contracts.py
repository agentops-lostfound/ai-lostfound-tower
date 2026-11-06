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
MVP_CATEGORIES = ["지갑", "USB", "립밤", "모형폰", "핸드크림", "보조배터리"]  # 11/5 셀프서비스 MVP: 6종 모두 사용
FEATURE_FIELDS = ["color", "shape", "mark", "visible_text", "material"]
PRIVATE_FIELDS = ["mark", "visible_text"]   # 확인 질문용 비공개 특징(후보 카드에 안 보임)
# 11/4: "분홍" 추가 — 구매한 카드지갑 중 하나가 핑크샌드(임시, 실물 도착 뒤 바뀔 수 있음). 없으면 "기타"로 뭉개져 색으로 구별 못 함
#        (김건태 매칭 korean_query·정책은 pink 를 이미 다룸 → 관제탑 목록만 맞춤)
COLORS = ["검정", "흰색", "회색", "빨강", "파랑", "남색", "초록", "노랑", "갈색", "분홍", "기타"]
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
# 11/4: 가상 시연용 서면역 등록기계 KIOSK-C 추가(디스코드 "서면역 ○번 출구에서 주웠어요" 시연, docs/design/virtual_demo.md)
#   앞글자는 C 가 아니라 S(Seomyeon): C 로 하면 접수 번호 C-20261104-0001 이 찾기 번호(C-날짜-순번)와 똑같아진다
MACHINE_LETTERS = {"KIOSK-A": "A", "KIOSK-C": "S", "CENTER": "H"}   # 해운대 A · 서면 S · 본센터(부산역) 직접 접수 H (11/6 중앙역 삭제)

# 습득자 연락처(finder_contact) 보관: 인계 완료 뒤 30일이 지나면 지운다(tools/purge_contacts.py)
CONTACT_RETENTION_DAYS = 30

# 물건 상태(기준 문서 3장)
# 11/4: 로봇이 바구니에 넣은 것(인계 대기)과 직원이 분실인에게 건넨 것(인계 완료)을 나눴다
#       인계 완료는 직원 화면의 "분실인에게 건넴" 확인(POST /returns/{case_id}/handover)으로만 바뀐다
ITEM_STATUS = ["등록기계 보관", "회수 중", "본센터 보관", "확인 중", "승인·수령 예약", "반환 중", "인계 대기", "인계 완료", "반환 보류"]
HANDOVER_WAIT = "인계 대기"
HANDOVER_DONE = "인계 완료"
HANDOVER_HOLD = "반환 보류"
# 인계 대기에서 직원이 건네지 않고 멈출 때 고르는 이유(자유 입력 없음 → 개인정보가 기록에 들어가지 않음)
HOLD_REASONS = ["본인 아님", "물건 다름", "분실인 거부", "기타"]
# 상태를 바꾼 주체(DB item_status_log.changed_by). 관제탑 반환 흐름 = tower, 직원 화면 인계·취소 = staff
CHANGED_BY = ["tower", "staff"]
# 직원 화면 정지 버튼을 누른 뒤 로봇 동작이 돌려받는 실패 이유(재시도하지 않음)
STAFF_STOP_REASON = "직원 정지 버튼"
# 본센터 보관함에 있을 수 있는 상태(닮은 물건 검사 대상). 등록기계 보관·인계 대기(바구니)·인계 완료는 보관함에 없다
ACTIVE_STATUSES = [s for s in ITEM_STATUS if s not in ("등록기계 보관", HANDOVER_WAIT, HANDOVER_DONE)]

# 메인 AI 결정
DECISION_RETURNED = "returned"        # 바구니까지 전달 완료(물건 상태는 인계 대기, 직원이 건네면 인계 완료)
DECISION_REJECTED = "rejected"        # 안전 규칙에 막혀 반환하지 않음
DECISION_STAFF = "staff_check"        # 자동으로 정하지 않고 직원 확인으로 넘김
DECISION_STOPPED = "stopped"          # 로봇 동작 중 실패로 정지
DECISIONS = [DECISION_RETURNED, DECISION_REJECTED, DECISION_STAFF, DECISION_STOPPED]

# 로봇 좌표(11/4): 로봇에는 픽셀이 아니라 작업대 기준 mm 좌표 [x, y] 를 넘긴다(탑뷰 ArUco 보정 결과 center_mm)
#   mm 좌표가 없거나(보정 안 됨) 숫자가 아니면 관제탑은 로봇을 움직이지 않고 직원 확인으로 보낸다
#   작업대 mm → 로봇 기준 좌표·높이·자세 변환은 로봇 부품 안에서 한다(김건태 LF-21)
def valid_point_mm(v) -> bool:
    """[x, y] 두 숫자(유한값)면 True. None·빈 목록·문자·NaN 은 False."""
    import math
    return (isinstance(v, (list, tuple)) and len(v) == 2
            and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v))


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
