"""가상 세계와 가상 부품 — 전체 가상 시연(LF-29, 11/4, docs/design/virtual_demo.md).

한줄 설명: 등록기계·Qwen·탑뷰 카메라·로봇팔을 "움직임까지 보이는 가짜"로 만들어, 진짜 부품 없이도
습득 → 회수 → 찾기 → 반환 → 인계 전체가 관제탑의 진짜 코드(서비스·반환 흐름·매칭·안전 규칙)를 그대로 지나가게 한다.

교체 원칙(진짜로 합칠 때 관제탑 코드는 고치지 않는다)
    가상 부품          | 지키는 약속(함수 모양)                         | 진짜 부품으로 바꾸는 법
    SimWorld(접수 저장) | IntakeStore: places · create · set_features   | TOWER_DB=1 → PostgresIntakeStore
    SimWorld.db         | db_get_item · db_set_status · db_list_active  | TOWER_DB=1 → PostgresDbPart
    sim_qwen()          | Qwen general_items_v1 특징(영어) → POST /items/{id}/features | 김건태 Qwen 작업이 같은 주소로 보냄
    SimTopview          | vision_topview() → result_with_qwen.json 모양 → adapt_report | TOWER_VISION_FILE=결과 폴더
    SimRobot            | robot_approach(mm, px) · grasp · verify · deliver · stop · home | 로봇 부품(LF-11·19·21)을 robot= 에 꽂음

- 세계(SimWorld)는 "물건이 실제로 어디 있는지"(등록기계·이동 중·보관함 칸·그리퍼·바구니)와 로봇팔 위치를 기억한다.
  관제탑의 상태(DB status)와 별개다 → 매칭이 엉뚱한 물건을 고르면 세계에서도 엉뚱한 물건이 바구니로 간다(숨기지 않음)
- 시간: speed 배수(기본 1.0, 0 이면 기다리지 않음 = 시험용). 실패 흉내: inject(grasp_fail=1, calib_fail=True)
- 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import copy
import re
import threading
import time
from datetime import date, datetime, timezone

from agents.contracts import (ACTIVE_STATUSES, HANDOVER_DONE, HANDOVER_HOLD, MACHINE_LETTERS, NONE, STAFF_STOP_REASON,
                              UNKNOWN, make_item_id, robot_result)
from agents.intake import DEMO_PLACES, IntakeError, split_features
from agents.vision_adapter import RESULT_NAME, adapt_report, to_features  # noqa: F401 (RESULT_NAME: 문서용)

# ---------- 작업대 좌표(가상, mm) ----------
# 11/7: 실제 판(docs/design/storage_slots.md)과 같게 — 보관판 500 × 250 mm, 로봇팔은 아래쪽 긴 변, 제출보관함(H-1, 20×20cm)은
# 반대쪽 긴 변(위) 가운데. 한 행 = 로봇 쪽(1)·먼 쪽(2) 칸 2개, 행 4개가 긴 변 방향(왼→오).
# 11/9 사용자 결정: R1(왼쪽 두 칸) = 휴대폰 전용(사선이라 간격이 넓음) · R2~R4 = 그 밖 5종(행 제한 없음). 칸 이름·품목은 정답지 LAYOUT 과 같다
BENCH_MM = (560.0, 620.0)
BIN_MM = (0.0, 240.0, 500.0, 490.0)                   # 보관판 x1, y1, x2, y2
SLOT_IDS = ["R1-1", "R1-2", "R2-1", "R2-2", "R3-1", "R3-2", "R4-1", "R4-2"]
_ROW_X = {"R1": 70.0, "R2": 205.0, "R3": 325.0, "R4": 445.0}
_SLOT_Y = {"1": 420.0, "2": 310.0}                    # 1 = 로봇 쪽(가까움), 2 = 먼 쪽
SLOTS_MM = [(_ROW_X[sid[:2]], _SLOT_Y[sid[3]]) for sid in SLOT_IDS]   # 보관 칸 8개(순서 = SLOT_IDS)
# 11/9 실제 규격(사용자 실측): 보관판 500×250, 테두리 마킹테이프 15mm. 로봇 쪽 아래에 15mm 덧댄 띠(받침 앞 돌출부 두 개 폭)로 가운데 맞춤.
# 제출보관함 H-1(200×200, 테두리 테이프)은 보관판 위쪽 가운데에 딱 붙임
TAPE_MM = 15.0
HBOX_MM = (150.0, 40.0, 350.0, 240.0)                # 제출보관함 H-1 (20 × 20 cm), 보관판 위 가장자리에 붙음
# 로봇이 내려놓는 곳 = H-1 의 로봇 쪽 절반(보관판 끝에서 50mm 안). 실제 크기 팔은 H-1 한가운데(회전축에서 약 391mm)에
# 수직으로는 못 닿고, 집게를 30~45° 기울이면 이 자리(약 341mm)에 놓을 수 있다(11/9 관절 범위 전체 계산)
BASKET_MM = ((HBOX_MM[0] + HBOX_MM[2]) / 2, HBOX_MM[3] - 50.0)
HOME_MM = (250.0, 360.0)                   # 원점(대기) 자세의 집게 끝 — 실제 SO-101 관절 한계 안
# 받침 원점 위치: 회전축이 받침 앞 돌출부 끝에서 25.8mm 뒤(공식 STL) + 덧댄 띠 15mm → 보관판 아래 끝(490)에서 40.8mm 바깥
ROBOT_BASE_MM = (250.0, 490.0 + 15.0 + 25.8 + 38.84)
MARKERS_MM = [(12.0, 252.0), (488.0, 478.0)]          # ArUco 표식 2개(보관판 대각선)
# 로봇 쪽 덧댄 띠(가로 약 66mm = 받침 앞 돌출부 두 개의 양 끝 폭, 세로 15mm), 보관판 아래 끝 가운데 — 그림용 x1, y1, x2, y2
SHIM_MM = (250.0 - 33.0, BIN_MM[3], 250.0 + 33.0, BIN_MM[3] + 15.0)
CAMERA_HEIGHT_MM = 500.0                              # 탑뷰 카메라 높이(사용자 정보, 약) — 보관함과 로봇팔을 위에서 내려다봄
PX_SCALE, PX_OFFSET = 1.4, (40.0, 30.0)              # 탑뷰 사진 픽셀 = mm × 1.4 + 여백(가상 1360×900 사진 안)


def slot_rows() -> dict[str, list[str]]:
    """행 코드 → 받는 품목(빈 목록 = 제한 없음). 보관함 정답지 LAYOUT 그대로"""
    from agents.storage import LAYOUT
    return {code: list(allowed) for code, _label, kind, allowed, _n, _note in LAYOUT if kind == "shelf"}
PICK_RADIUS_MM = 35.0                                 # 접근 좌표에서 이 거리 안의 물건을 집는다

# ---------- 물건이 있는 곳(세계) ----------
LOC_KIOSK, LOC_TRANSIT, LOC_BIN, LOC_GRIPPER, LOC_BASKET, LOC_HANDED, LOC_STAFF = (
    "kiosk", "transit", "bin", "gripper", "basket", "handed", "staff")
LOC_SHELF = "shelf"          # 11/9 직원 보관 선반(보관판 밖, 로봇이 집지 않음 — 반환은 직원이 직접 건넴)

STATIONS = {"서면": "KIOSK-C", "해운대": "KIOSK-A"}   # 말에 나오는 역 이름 → 등록기계
MACHINE_STATION = {v: k for k, v in STATIONS.items()}


def mm_to_px(x: float, y: float) -> list[float]:
    return [round(PX_OFFSET[0] + x * PX_SCALE, 1), round(PX_OFFSET[1] + y * PX_SCALE, 1)]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------- 가상 Qwen: 말(설명) → Qwen general_items_v1 특징(영어) ----------
# 진짜 Qwen 은 사진을 보고 같은 모양의 JSON 을 낸다. 가상 시연에서는 디스코드 메시지 글이 "사진" 역할을 한다
CATEGORY_WORDS = [("보조배터리", "power_bank"), ("배터리", "power_bank"), ("카드지갑", "card_wallet"),
                  ("반지갑", "card_wallet"), ("장지갑", "card_wallet"), ("지갑", "card_wallet"), ("usb", "usb"),
                  ("유에스비", "usb"), ("립밤", "lip_balm"), ("핸드크림", "hand_cream"), ("모형폰", "phone"),
                  ("휴대폰", "phone"), ("핸드폰", "phone"), ("스마트폰", "phone")]
COLOR_WORDS = [("검정", "black"), ("검은", "black"), ("까만", "black"), ("블랙", "black"), ("하얀", "white"),
               ("흰", "white"), ("화이트", "white"), ("회색", "gray"), ("그레이", "gray"), ("은색", "silver"),
               ("실버", "silver"), ("빨간", "red"), ("빨강", "red"), ("레드", "red"), ("남색", "navy"),
               ("네이비", "navy"), ("파란", "blue"), ("파랑", "blue"), ("블루", "blue"), ("초록", "green"),
               ("녹색", "green"), ("노란", "yellow"), ("노랑", "yellow"), ("갈색", "brown"), ("브라운", "brown"),
               ("분홍", "pink"), ("핑크", "pink")]
MATERIAL_WORDS = [("가죽", "leather"), ("플라스틱", "plastic"), ("금속", "metal"), ("메탈", "metal"), ("천", "fabric")]
STICKER_SHAPES = [("별", "star"), ("하트", "heart"), ("동그라미", "circle"), ("원형", "circle"), ("네모", "square")]
DEFAULT_SHAPE = {"card_wallet": "rectangular", "usb": "stick", "power_bank": "rectangular", "lip_balm": "cylinder",
                 "hand_cream": "tube", "phone": "rectangular"}
DEFAULT_MATERIAL = {"card_wallet": ["synthetic leather"], "usb": ["metal", "plastic"], "power_bank": ["plastic"],
                    "lip_balm": ["plastic"], "hand_cream": ["plastic"], "phone": ["plastic"]}
TAGS = {"#집기실패": "grasp_fail", "#보정실패": "calib_fail", "#신분증불일치": "id_mismatch", "#수동인계": "manual_handover",
        "#흐린촬영": "blur_once"}      # 11/8: 첫 탑뷰에서 색·글자를 못 읽음 → 매칭 애매 → 관제탑 메인 AI 가 다시 찍게 함(TOWER_BRAIN=1)
_LATIN = re.compile(r"\b[A-Za-z][A-Za-z0-9]{1,15}\b")
_QUOTED = re.compile(r"[\"'“”‘’]([^\"'“”‘’]{1,20})[\"'“”‘’]")


def split_tags(text: str) -> tuple[str, set[str]]:
    """메시지 끝의 실패 흉내 꼬리표(#집기실패 등)를 떼어 낸다. (남은 글, 꼬리표 이름들)"""
    tags = {name for tag, name in TAGS.items() if tag in (text or "")}
    for tag in TAGS:
        text = (text or "").replace(tag, " ")
    return re.sub(r"\s+", " ", text).strip(), tags


def _first(text: str, table) -> str | None:
    low = text.lower()
    hits = [(low.find(w), en) for w, en in table if w in low]
    return min(hits)[1] if hits else None


def sim_qwen(text: str, query: bool = False) -> dict:
    """설명 글 → Qwen general_items_v1 모양(영어). query=True(분실인 설명)면 말하지 않은 것은 비워 둔다(모름)."""
    text = text or ""
    cat = _first(text, CATEGORY_WORDS)
    color = _first(text, COLOR_WORDS)
    material = _first(text, MATERIAL_WORDS)
    words = [w for w in _LATIN.findall(text) if w.lower() != "usb"] + _QUOTED.findall(text)
    sticker_status, stickers = ("unknown" if query else "absent"), []
    if "스티커" in text:
        if re.search(r"스티커\s*(는|가)?\s*(없|안\s*붙)", text):
            sticker_status = "absent"
        else:
            shape = _first(text, STICKER_SHAPES) or "small"
            sticker_status, stickers = "present", [{"shape": shape, "position": None}]
    shape = None
    if re.search(r"네모|직사각", text):
        shape = "rectangular"
    elif not query and cat:
        shape = DEFAULT_SHAPE.get(cat)
    mats = [material] if material else ([] if query else list(DEFAULT_MATERIAL.get(cat, [])))
    return {"category": cat or "unknown", "colors": [color] if color else [], "shape": shape, "materials": mats,
            "logos_or_text": list(dict.fromkeys(words)), "sticker_status": sticker_status, "stickers": stickers,
            "distinctive_features": []}


def query_features(text: str) -> dict:
    """분실인 설명 → 계약 특징(한국어). 말한 칸만 남긴다(모르는 칸은 비교하지 않음)."""
    q = sim_qwen(text, query=True)
    f = to_features(q, 0.9)
    f.pop("confidence", None)
    if q["sticker_status"] == "unknown":
        f.pop("mark", None)
    return {k: v for k, v in f.items() if v not in (UNKNOWN, "", None)}


def parse_place(text: str) -> tuple[str | None, str | None]:
    """습득 메시지 → (등록기계, 장소 글). 예: "서면역 5번 출구 앞에서 검정 지갑 주웠어요" → ("KIOSK-C", "서면역 5번 출구 앞")"""
    text = text or ""
    machine = next((m for st, m in STATIONS.items() if st in text), None)
    m = re.search(r"(.+?)(?:에서|에 떨어져|에 놓여)", text)
    place = m.group(1).strip() if m else None
    if place and machine:                          # "어제 서면역 …" 처럼 앞말이 붙으면 역 이름부터
        st = MACHINE_STATION[machine]
        place = place[place.find(st):] if st in place else place
    if not place and machine:
        place = f"{MACHINE_STATION[machine]}역"
    return machine, (place[:60] if place else None)


def lost_station(text: str) -> str | None:
    return next((st for st in STATIONS if st in (text or "")), None)


# ---------- 보관함 시연 물건(실제 구매 목록 기준, 11/4) ----------
# (이름, 가상 Qwen 이 '본' 설명). 실물이 오면 색·글자가 바뀔 수 있다 — 바뀌면 이 표만 고친다
#   카드지갑 3개(신지모루 맥세이프): 구매서에 "색 다르게 3개"만 있어 블랙·브라운·핑크샌드로 임시 설정(11/4 변재원). 블랙은 신고용으로 비움
#   목업폰(아이폰17 목업): 화이트·블랙·블루 구매 → 블랙은 신고용으로 비움
#   USB: 샌디스크 울트라 듀얼드라이브 2개(같은 제품) + 액센 SK31 1개(신고용). 샌디스크 색은 은색(추정)
#   보조배터리(스피디 슬림 듀얼) 2개 중 1개만 보관함, 색 흰색(추정). 핸드크림(부케가르니) 흰색(추정)
#   11/7: 보관 칸이 8개(실제 판)라 8개를 다 넣으면 습득 시연 물건을 넣을 칸이 없다 → 5개만 넣는다.
#   11/9: 휴대폰 칸(R1) 2개는 시작부터 참(휴대폰 습득 → 바로 '칸 대기' 장면), 그 밖 6칸은 로봇 쪽 1번 줄 3칸만 차고 2번 줄 3칸이 빈다
SEED_ITEMS = [
    ("목업폰 화이트", "화이트 모형폰"),        # → R1-1
    ("목업폰 블루", "블루 모형폰"),            # → R1-2
    ("USB 샌디스크 1", "은색 USB SanDisk"),    # → R2-1 (같은 제품 2개 → '닮은 물건 → 직원 확인' 장면)
    ("USB 샌디스크 2", "은색 USB SanDisk"),    # → R3-1
    ("카드지갑 브라운", "브라운 카드지갑"),    # → R4-1
]


# ---------- SO-101 로봇팔 관절(11/4, docs/progress/soarm-local-handoff.md 와 같은 번호) ----------
# 리더(검정)·팔로워(흰색) 모두 STS3215 모터 6개 = 움직이는 축 5개 + 그리퍼 1개. 리더는 그리퍼 대신 손잡이(트리거)
# 학습: 리더로 팔로워를 움직이며 에피소드 녹화(관절 값 + 카메라 영상) → 정책 학습(SmolVLA, ACT 비교) → 시연 때는 팔로워만 정책으로 움직임
SO101_JOINTS = [("shoulder_pan", "좌우 회전"), ("shoulder_lift", "앞뒤 숙임"), ("elbow_flex", "두 긴 팔 접힘"),
                ("wrist_flex", "끝부분 위아래"), ("wrist_roll", "끝부분 회전"), ("gripper", "집게 열림")]
HOME_Z, HOME_GRIP = 100.0, 30.0        # 원점 자세: 집게 높이(mm) · 집게 열림(%)
HOVER_Z, PICK_Z, DROP_Z = 90.0, 15.0, 60.0

# 실제 SO-101 치수(mm) — SO-ARM100 공식 MuJoCo 모델 so101_new_calib(Apache-2.0)에서 읽음, tools/so101_shape.py 로 검사
# 팔 평면(좌우 회전축에서 앞쪽 거리 r, 바닥에서 높이 z) 기준. 관절 0° = 위팔 거의 수직 · 아래팔·손목 수평인 'ㄱ' 자세
SO101_PAN_X = 38.84                                   # 받침 원점 → 좌우 회전축(앞쪽)
SO101_SHOULDER = (30.40, 116.60)                      # 좌우 회전축 → 어깨(앞뒤 숙임) 축 (r, z)
SO101_UPPER = (28.00, 112.57)                         # 어깨 → 팔꿈치 (관절 0° 때 r, z)
SO101_FORE = (134.90, 5.20)                           # 팔꿈치 → 손목
SO101_TOOL = (159.30, -7.90)                          # 손목 → 집게 끝(gripperframe)
SO101_LIMITS = {"shoulder_pan": (-110.0, 110.0), "shoulder_lift": (-100.0, 100.0), "elbow_flex": (-96.8, 96.8),
                "wrist_flex": (-95.0, 95.0), "wrist_roll": (-157.2, 162.8), "gripper": (0.0, 100.0)}
SO101_GRIP_DEG = (-10.0, 100.0)                       # 집게 관절 각도 범위(0% 닫힘 ~ 100% 열림, 화면 그림용)
# 11/9: 실제 규격 배치로 바꾸고 실제 크기(1.0)로 그린다(예전 1.6배는 H-1 을 한가운데에 수직으로 놓으려던 가정 때문)
ARM_SCALE = 1.0


def so101_joints(x: float, y: float, z: float, gripper: float, roll: float = 0.0, scale: float | None = None) -> dict:
    """집게 끝 위치(작업대 mm, 높이 z)·열림 → 관절 6개 각도(도, 그리퍼는 %). 실제 SO-101 기구(배율 scale)로 푼 값이다.
    각도 부호는 공식 모델과 같다: 좌우 + = 오른쪽, 숙임·접힘·손목 + = 앞·아래로. 진짜 로봇 값은 보정값으로 읽는다(추정과 다를 수 있음).
    집게는 되도록 바닥을 수직으로 보게 하고, 손목 한계를 넘으면 앞으로 조금씩 기울인다(원점처럼 몸 가까운 자세)."""
    import math
    s = ARM_SCALE if scale is None else scale
    dx, dy = x - ROBOT_BASE_MM[0], ROBOT_BASE_MM[1] - y
    pan = math.degrees(math.atan2(dx, dy))                     # 0 = 보관함 쪽 정면, + = 오른쪽
    r = math.hypot(dx, dy)
    l1, l2, l3 = (math.hypot(*v) * s for v in (SO101_UPPER, SO101_FORE, SO101_TOOL))
    a1z, a2z, a3z = (math.atan2(v[1], v[0]) for v in (SO101_UPPER, SO101_FORE, SO101_TOOL))   # 0° 자세의 각 마디 방향
    sx, sz = SO101_SHOULDER[0] * s, SO101_SHOULDER[1] * s
    best = None
    # 11/9: 실제 크기 팔 검증에서 찾은 문제 — 닿지 않는 거리를 잘라 맞춘 해를 '관절 한계 안'이라고 골라 집게 끝이 26~86mm 어긋났다.
    # → 닿는 해(거리 오차 0)를 먼저, 그중 관절 한계 안이고 집게가 가장 수직에 가까운 해. 팔꿈치 위·아래 두 해를 모두 본다
    for tilt in range(0, 95, 5):                                # 집게 기울기: 0 = 수직 아래(11/9: 90°까지 — H-1 은 기울여 놓음)
        pitch = math.radians(-90 + tilt)
        wx, wz = r - l3 * math.cos(pitch), z - l3 * math.sin(pitch)        # 손목 축 위치
        vx, vz = wx - sx, wz - sz
        raw = max(math.hypot(vx, vz), 1e-6)
        miss = max(0.0, raw - (l1 + l2), abs(l1 - l2) - raw)    # 손목이 닿지 않는 거리(mm)
        d = min(max(raw, abs(l1 - l2) + 1e-6), l1 + l2 - 1e-6)
        c = max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)))
        for sign in (1, -1):                                    # 1 = 팔꿈치가 위로 가는 해, -1 = 아래
            a1 = math.atan2(vz, vx) + sign * math.acos(c)
            ex, ez = sx + l1 * math.cos(a1), sz + l1 * math.sin(a1)
            a2 = math.atan2(wz - ez, wx - ex)
            lift = math.degrees(a1z - a1)
            elbow = math.degrees(a2z - a2) - lift
            wrist = math.degrees(a3z - pitch) - lift - elbow
            lift, elbow, wrist = ((v + 180) % 360 - 180 for v in (lift, elbow, wrist))
            j = {"shoulder_pan": pan, "shoulder_lift": lift, "elbow_flex": elbow, "wrist_flex": wrist}
            over = sum(max(0.0, lo - v, v - hi) for k, v in j.items() for lo, hi in [SO101_LIMITS[k]])
            key = (miss > 0.5, over > 0, miss + over, tilt)
            if best is None or key < best[0]:
                best = (key, j)
        if best[0][:2] == (False, False):
            break
    j = best[1]
    return {"shoulder_pan": round(j["shoulder_pan"], 1), "shoulder_lift": round(j["shoulder_lift"], 1),
            "elbow_flex": round(j["elbow_flex"], 1), "wrist_flex": round(j["wrist_flex"], 1),
            "wrist_roll": round(roll, 1), "gripper": round(max(0.0, min(100.0, gripper)), 1)}


def so101_tip(j: dict, scale: float | None = None) -> tuple[float, float, float]:
    """관절 각도(도) → 집게 끝 (작업대 x, y, 높이 z). so101_joints 의 반대(검사·도달 범위 계산용)."""
    import math
    s = ARM_SCALE if scale is None else scale
    lift, elbow, wrist = (math.radians(j[k]) for k in ("shoulder_lift", "elbow_flex", "wrist_flex"))
    r, z = SO101_SHOULDER[0] * s, SO101_SHOULDER[1] * s
    turn = 0.0
    for v, dq in ((SO101_UPPER, lift), (SO101_FORE, elbow), (SO101_TOOL, wrist)):
        turn += dq                                             # 숙임·접힘·손목은 모두 같은 방향(+ = 앞·아래)으로 돈다
        a = math.atan2(v[1], v[0]) - turn
        r += math.hypot(*v) * s * math.cos(a)
        z += math.hypot(*v) * s * math.sin(a)
    pan = math.radians(j["shoulder_pan"])
    return ROBOT_BASE_MM[0] + r * math.sin(pan), ROBOT_BASE_MM[1] - r * math.cos(pan), z


def so101_reach(z: float = PICK_Z, scale: float = 1.0) -> float:
    """집게를 높이 z 까지 내릴 수 있는 가장 먼 거리(좌우 회전축에서 mm). 관절 한계 안 · 집게 끝이 목표에 닿을 때만 인정."""
    import math
    best = 0.0
    for r in range(20, 700, 2):
        x, y = ROBOT_BASE_MM[0], ROBOT_BASE_MM[1] - r
        j = so101_joints(x, y, z, 50, scale=scale)
        tx, ty, tz = so101_tip(j, scale)
        ok = all(SO101_LIMITS[k][0] <= v <= SO101_LIMITS[k][1] for k, v in j.items())
        if ok and math.dist((tx, ty, tz), (x, y, z)) < 1.0:
            best = float(r)
    return best


_REAL_REACH = None   # 실제 크기 팔이 바닥(집기 높이)까지 닿는 거리 — 처음 쓸 때 계산


# ---------- 가상 세계 ----------
class SimWorld:
    """가상 시연의 세계 하나(관제탑이 켜져 있는 동안 기억). IntakeStore 와 DB 부품 역할도 같이 한다."""

    def __init__(self, speed: float = 1.0, seed: bool = True, today: date | None = None):
        self.speed = max(0.0, float(speed))
        self._lock = threading.RLock()
        self.today = today
        self.items: dict[str, dict] = {}
        self.contacts: dict[str, dict] = {}       # 저장 여부 확인용(밖으로 나가지 않음)
        self._places = [{"place_id": i + 1, "machine_id": m, "label": label, "use_count": 0}
                        for i, (m, label) in enumerate((m, l) for m, ls in DEMO_PLACES.items() for l in ls)]
        self.arm = {"x": HOME_MM[0], "y": HOME_MM[1], "z": HOME_Z, "gripper": HOME_GRIP, "phase": "대기",
                    "holding": None, "stopped": False, "target": None, "joints": so101_joints(*HOME_MM, HOME_Z, HOME_GRIP)}
        self.homing: threading.Thread | None = None
        self._seq: dict[str, int] = {}                 # 접수 번호 앞부분별 마지막 순번(초기화해도 유지)    # 바구니에 내려놓은 뒤 원점으로 돌아가는 중(뒤에서)
        self.faults = {"grasp_fail": 0, "calib_fail": False, "blur": False}
        self.version = 0
        # 11/7 보관함 정답지와 맞추기(build_sim_service 가 연결): 칸에 넣을 때 알림 · 정답지가 예약한 칸 · 그 물건의 칸
        self.on_bin = None          # (item_id, slot_id) → None
        self.reserved = None        # () → {slot_id: item_id}
        # 11/9 보관함이 꽉 찼을 때: 회수하러 간 물건이 미리 잡아 둔 칸 · 칸이 없어 등록기계에 둔 물건(먼저 온 순서)
        self.collecting: dict[str, int] = {}
        self.wait_queue: list[str] = []
        self.on_freed = None        # () → None. 칸이 비면(인계 완료) 연출기가 대기 물건을 회수하게 알림
        if seed:
            self.seed()

    # ----- 공통 -----
    def sleep(self, seconds: float) -> None:
        if self.speed > 0 and seconds > 0:
            time.sleep(seconds * self.speed)

    def _touch(self) -> None:
        self.version += 1

    def inject(self, grasp_fail: int | None = None, calib_fail: bool | None = None, blur: bool | None = None) -> None:
        """실패 흉내 켜기(가상 시연에서 안전 규칙을 보여 주려고)."""
        with self._lock:
            if blur is not None:
                self.faults["blur"] = bool(blur)
            if grasp_fail is not None:
                self.faults["grasp_fail"] = max(0, int(grasp_fail))
            if calib_fail is not None:
                self.faults["calib_fail"] = bool(calib_fail)

    def seed(self) -> None:
        """보관함에 미리 있는 물건(본센터 직접 접수 H-…) — 실제 구매 목록(구매요구서_2조_AgentOps_최종, 11/3) 기준 5개(11/7, 칸 8개).
        디스코드로 신고해 볼 물건(검정 카드지갑·목업폰 블랙·보조배터리 2번째·액센 USB·립밤)은 일부러 비워 둔다.
        같은 제품 2개(USB 샌디스크)를 넣어 '닮은 물건 → 직원 확인' 장면이 실제처럼 나오게 한다. 색·글자는 SEED_ITEMS 주석 참고."""
        for _, text in SEED_ITEMS:
            row = self.create({"machine_id": "CENTER", "place_id": None, "place_text": "본센터 접수(시연)",
                               "finder": None, "photo_path": None})
            q = sim_qwen(text)
            self.set_features(row["item_id"], to_features(q, 0.9), qwen=q)
            self.items[row["item_id"]]["status"] = "본센터 보관"
            self.move(row["item_id"], LOC_BIN)
        self._touch()

    # ----- IntakeStore (등록기계 접수) -----
    def places(self, machine_id: str, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = sorted((p for p in self._places if p["machine_id"] == machine_id),
                          key=lambda p: (-p["use_count"], p["place_id"]))
            return [{"place_id": p["place_id"], "label": p["label"]} for p in rows[:limit]]

    def create(self, intake: dict, today: date | None = None) -> dict:
        day = today or self.today or date.today()
        with self._lock:
            if intake.get("place_id") is not None:
                p = next((p for p in self._places if p["place_id"] == intake["place_id"]
                          and p["machine_id"] == intake["machine_id"]), None)
                if p is None:
                    raise IntakeError("place_id: 이 등록기계의 추천 장소가 아닙니다")
                p["use_count"] += 1
            prefix = f"{MACHINE_LETTERS[intake['machine_id']]}-{day:%Y%m%d}-"
            # 초기화해도 번호는 이어진다(11/4 무작위 시험: 디스코드에 남은 옛 진행판 번호와 새 물건 번호가 겹쳤음)
            seq = max(self._seq.get(prefix, 0), sum(1 for k in self.items if k.startswith(prefix))) + 1
            self._seq[prefix] = seq
            item_id = make_item_id(intake["machine_id"], day, seq)
            row = {"item_id": item_id, "machine_id": intake["machine_id"], "place_id": intake.get("place_id"),
                   "place_text": intake["place_text"], "photo_path": intake.get("photo_path"),
                   "received_at": _now_iso(), "status": "등록기계 보관", "category": UNKNOWN, "features": {},
                   "private_features": {}, "contact_saved": intake.get("finder") is not None,
                   "qwen": None, "loc": LOC_KIOSK, "slot": None, "changed_by": "kiosk"}
            self.items[item_id] = row
            if intake.get("finder"):
                self.contacts[item_id] = dict(intake["finder"])
            self._touch()
            return {k: copy.deepcopy(v) for k, v in row.items() if k not in ("qwen", "loc", "slot")}

    def set_features(self, item_id: str, feats: dict, qwen: dict | None = None) -> bool:
        cat, pub, priv = split_features(feats)
        with self._lock:
            row = self.items.get(item_id)
            if row is None:
                return False
            if row.get("features") and row.get("status") != "등록기계 보관":   # 11/8 보관 중인 물건 특징 덮어쓰기 금지
                raise IntakeError("이미 특징이 채워진 물건입니다(덮어쓰지 않음)")
            row.update(category=cat, features=pub, private_features=priv)
            if qwen is not None:
                row["qwen"] = copy.deepcopy(qwen)
            self._touch()
            return True

    def remember_qwen(self, item_id: str, qwen: dict) -> None:
        """등록기계에서 본 Qwen 원본을 기억 → 가상 탑뷰가 보관함에서 같은 물건을 다시 '찍을' 때 쓴다."""
        with self._lock:
            if item_id in self.items:
                self.items[item_id]["qwen"] = copy.deepcopy(qwen)

    # ----- DB 부품(관제탑 반환 흐름이 부름) -----
    def _record(self, row: dict) -> dict:
        feats = {**({"category": row["category"]} if row.get("category") not in (None, UNKNOWN) else {}),
                 **row.get("features", {}), **row.get("private_features", {})}
        feats.pop("confidence", None)
        return {"item_id": row["item_id"], "status": row["status"], "category": row.get("category"),
                "features": copy.deepcopy(feats), "object_id": None}

    def pending_photos(self, limit: int = 10) -> list[dict]:
        """11/7 사진 분석 대기(진짜 키오스크 사진 → 관제탑 PC Qwen 작업자 tools/intake_qwen_worker.py)"""
        from agents.intake import is_pending_photo, pending_row
        with self._lock:
            rows = [r for r in self.items.values() if is_pending_photo(r)]
        return [pending_row(r) for r in sorted(rows, key=lambda r: (r["received_at"], r["item_id"]))[:limit]]

    def chat_items(self) -> list[dict]:
        """11/7 챗봇 물건 검색용(읽기 전용 복사본): 공개 특징(색 등)만, 비공개 특징·연락처는 넣지 않는다"""
        with self._lock:
            return [{"item_id": r["item_id"], "category": r.get("category"), "status": r["status"],
                     "machine_id": r.get("machine_id"), "received_at": r.get("received_at"),
                     "features": {"color": (r.get("features") or {}).get("color")}} for r in self.items.values()]

    def db_get_item(self, item_id: str) -> dict | None:
        with self._lock:
            row = self.items.get(item_id)
            return None if row is None else self._record(row)

    def db_set_status(self, item_id: str, status: str, changed_by: str = "tower") -> dict:
        cur = self.items.get(item_id)                          # 되돌림(보류→보관)일 때만 정답지를 읽는다 — 보관 화면 '넣기'는
        res = (self._reserved() if status == "본센터 보관" and cur and cur["loc"] in (LOC_STAFF, LOC_BASKET)
               else {})                                        # 정답지 잠금 안에서 이 함수를 부르므로 읽으면 교착(잠금 밖)
        with self._lock:
            row = self.items.get(item_id)
            if row is None:
                return robot_result(False, "물건 기록 없음")
            row["status"], row["changed_by"] = status, changed_by
            if status == "본센터 보관" and row["loc"] in (LOC_STAFF, LOC_BASKET):   # 11/7 반환 보류 → 원래 칸으로 되돌림
                sid = next((k for k, v in res.items() if v == item_id and k in SLOT_IDS), None)
                i = SLOT_IDS.index(sid) if sid else self.free_slot(row.get("category"), item_id, res)
                if i is not None:
                    row["slot"], row["loc"] = i, LOC_BIN
            if status == HANDOVER_DONE and row["loc"] in (LOC_BASKET, LOC_SHELF):
                row["loc"] = LOC_HANDED                # 직원이 바구니(또는 직원 보관 선반)에서 꺼내 분실인에게 건넴
            elif status == HANDOVER_HOLD and row["loc"] == LOC_BASKET:
                row["loc"] = LOC_STAFF                 # 직원이 꺼내 따로 보관
            self._touch()
        if status == HANDOVER_DONE and self.on_freed:   # 11/9 칸 예약이 풀림 → 칸 대기 물건 회수(잠금 밖에서)
            try:
                self.on_freed()
            except Exception:
                pass
        return robot_result(True)

    def db_list_active(self) -> list[dict] | None:
        with self._lock:
            return [self._record(r) for r in self.items.values() if r["status"] in ACTIVE_STATUSES]

    # ----- 물건 옮기기(회수 등, 사람이 하는 일) -----
    def _reserved(self) -> dict:
        """정답지가 예약한 칸 {slot_id: item_id}. 정답지는 자기 잠금 안에서 이 세계를 읽으므로
        반드시 이 세계의 잠금 밖에서 부른다(두 잠금이 서로 기다리는 교착 방지)"""
        try:
            return dict(self.reserved()) if self.reserved else {}
        except Exception:
            return {}

    def _taken(self, except_item: str | None, res: dict) -> set[int]:
        used = {r["slot"] for r in self.items.values() if r["loc"] == LOC_BIN and r["slot"] is not None
                and r["item_id"] != except_item}
        used |= {SLOT_IDS.index(sid) for sid, it in res.items() if sid in SLOT_IDS and it != except_item}
        used |= {i for it, i in self.collecting.items() if it != except_item}   # 11/9 회수하러 간 물건이 잡아 둔 칸
        return used

    def free_slot(self, category: str | None = None, item_id: str | None = None, res: dict | None = None) -> int | None:
        """빈 칸 고르기(보관함 정답지 recommend_slot 과 같은 규칙, 11/9): 그 품목을 받는 행(또는 제한 없는 행)의 빈 칸 중
        로봇에 가까운 칸(1번 줄)부터. 휴대폰 칸(R1)과 그 밖 칸(R2~R4)은 섞지 않는다 → 맞는 칸이 없으면 None(칸 대기·선반).
        품목을 모르면(시연 부품) 아무 빈 칸. 정답지가 이미 예약한 칸(반환 중·보류 물건의 원래 칸)은 비어 보여도 쓰지 않는다"""
        used = self._taken(item_id, self._reserved() if res is None else res)
        free = sorted((i for i in range(len(SLOTS_MM)) if i not in used),
                      key=lambda i: (SLOT_IDS[i].split("-")[1], SLOT_IDS[i]))        # 1번 줄(로봇 쪽) 먼저
        if not free:
            return None
        if category is None:
            return free[0]
        rows = slot_rows()
        for want in (lambda r: category in rows.get(r, []), lambda r: not rows.get(r)):
            hit = [i for i in free if want(SLOT_IDS[i][:2])]
            if hit:
                return hit[0]
        return None

    def reserve_slot(self, item_id: str, category: str | None) -> str | None:
        """11/9 회수하기 전에 칸 확인: 맞는 빈 칸이 있으면 그 칸을 이 물건 몫으로 잡아 두고 칸 번호, 없으면 None(칸 대기).
        잡아 둔 칸은 보관함에 넣거나(move) 선반으로 옮기면 풀린다"""
        res = self._reserved()                                  # 잠금 밖에서
        with self._lock:
            if item_id not in self.items:
                return None
            if item_id in self.collecting:
                return SLOT_IDS[self.collecting[item_id]]
            i = self.free_slot(category, item_id, res)
            if i is None:
                return None
            self.collecting[item_id] = i
            if item_id in self.wait_queue:
                self.wait_queue.remove(item_id)
            self._touch()
            return SLOT_IDS[i]

    def reserved_for(self, item_id: str) -> str | None:
        """회수하려고 잡아 둔 칸(없으면 None)"""
        with self._lock:
            i = self.collecting.get(item_id)
            return SLOT_IDS[i] if i is not None else None

    def add_wait(self, item_id: str) -> int:
        """칸 대기 줄에 넣기(이미 있으면 그대로). 줄에서의 순서(1부터)"""
        with self._lock:
            if item_id not in self.wait_queue:
                self.wait_queue.append(item_id)
                self._touch()
            return self.wait_queue.index(item_id) + 1

    def to_shelf(self, item_id: str) -> bool:
        """11/9 직원이 물건을 직원 보관 선반에 둠(보관 칸 → 선반, 또는 등록기계에서 바로 선반). 상태는 정답지가 바꾼다"""
        with self._lock:
            row = self.items.get(item_id)
            if row is None:
                return False
            row["loc"], row["slot"] = LOC_SHELF, None
            self.collecting.pop(item_id, None)
            if item_id in self.wait_queue:
                self.wait_queue.remove(item_id)
            self._touch()
            return True

    def put(self, item_id: str, slot_id: str) -> bool:
        """정해진 칸에 넣기(직원이 보관 화면에서 고른 칸, 반환 보류 물건을 원래 칸에)"""
        with self._lock:
            row = self.items.get(item_id)
            if row is None or slot_id not in SLOT_IDS:
                return False
            i = SLOT_IDS.index(slot_id)
            if any(r["loc"] == LOC_BIN and r["slot"] == i and r["item_id"] != item_id for r in self.items.values()):
                return False
            row["slot"], row["loc"] = i, LOC_BIN
            self._touch()
            return True

    def slot_id_of(self, item_id: str) -> str | None:
        r = self.items.get(item_id)
        return SLOT_IDS[r["slot"]] if r and r["loc"] == LOC_BIN and r["slot"] is not None else None

    def move(self, item_id: str, loc: str) -> bool:
        res = self._reserved() if loc == LOC_BIN else {}       # 잠금 밖에서
        with self._lock:
            row = self.items.get(item_id)
            if row is None:
                return False
            if loc == LOC_BIN:
                cat = row.get("category")
                slot = self.collecting.pop(item_id, None)       # 11/9 회수 전에 잡아 둔 칸
                if slot is None:
                    slot = self.free_slot(cat if cat not in (None, UNKNOWN) else None, item_id, res)
                if slot is None:
                    return False
                row["slot"] = slot
            elif row["loc"] == LOC_BIN and loc != LOC_BIN:
                row["slot"] = None
            row["loc"] = loc
            self._touch()
        if loc == LOC_BIN and self.on_bin:                 # 정답지(보관함 DB)에도 같은 칸으로(잠금 밖에서)
            try:
                self.on_bin(item_id, SLOT_IDS[row["slot"]])
            except Exception:
                pass
        return True

    def item_at(self, x: float, y: float) -> str | None:
        """보관함에서 (x, y) mm 가까이(PICK_RADIUS_MM) 있는 물건."""
        best = None
        for r in self.items.values():
            if r["loc"] != LOC_BIN or r["slot"] is None:
                continue
            sx, sy = SLOTS_MM[r["slot"]]
            d = ((sx - x) ** 2 + (sy - y) ** 2) ** 0.5
            if d <= PICK_RADIUS_MM and (best is None or d < best[0]):
                best = (d, r["item_id"])
        return best[1] if best else None

    # ----- 화면용 -----
    def snapshot(self) -> dict:
        global _REAL_REACH
        if _REAL_REACH is None:
            _REAL_REACH = so101_reach(PICK_Z, 1.0)
        with self._lock:
            items = []
            for r in self.items.values():
                pos = SLOTS_MM[r["slot"]] if r["loc"] == LOC_BIN and r["slot"] is not None else None
                items.append({"item_id": r["item_id"], "machine_id": r["machine_id"], "status": r["status"],
                              "loc": r["loc"], "category": r.get("category"), "color": r["features"].get("color"),
                              "place_text": r["place_text"], "mm": list(pos) if pos else None,
                              "slot_id": SLOT_IDS[r["slot"]] if pos else None,
                              "waiting": r["item_id"] in self.wait_queue})
            return {"version": self.version, "arm": dict(self.arm), "items": items,
                    "wait_queue": list(self.wait_queue),
                    "bench": {"size_mm": list(BENCH_MM), "bin_mm": list(BIN_MM), "basket_mm": list(BASKET_MM),
                              "home_mm": list(HOME_MM), "base_mm": list(ROBOT_BASE_MM),
                              "markers_mm": [list(m) for m in MARKERS_MM], "slots_mm": [list(s) for s in SLOTS_MM],
                              "slot_ids": list(SLOT_IDS), "rows": slot_rows(), "hbox_mm": list(HBOX_MM),
                              "tape_mm": TAPE_MM, "shim_mm": list(SHIM_MM), "camera_height_mm": CAMERA_HEIGHT_MM},
                    "faults": dict(self.faults),
                    "robot": {"model": "SO-101", "role": "팔로워(흰색) — 학습된 정책(SmolVLA)이 움직임",
                              "leader": "리더(검정) — 텔레오퍼레이션으로 학습 에피소드 녹화용(시연 때는 쓰지 않음)",
                              "joints": [{"id": i + 1, "name": n, "label": l, "unit": "%" if n == "gripper" else "°",
                                          "range": list(SO101_LIMITS[n])} for i, (n, l) in enumerate(SO101_JOINTS)],
                              "scale": ARM_SCALE, "real_reach_mm": _REAL_REACH, "grip_deg": list(SO101_GRIP_DEG), "pan_x": SO101_PAN_X,
                              "shape": "SO-ARM100 공식 MuJoCo 모델 so101_new_calib_camera(Apache-2.0)",
                              "cameras": ["탑뷰 카메라(보관함 위, 위치 찾기)", "손목 카메라(팔로워, 집기 때 VLA 입력)"]}}


# ---------- 가상 탑뷰 카메라 ----------
class SimTopview:
    """보관함을 '찍어' 김건태 vision/sequence.py 와 같은 result_with_qwen.json 모양을 만들고, 관제탑의 진짜 변환기
    (vision_adapter.adapt_report — 보정 관문 포함)로 바꿔 돌려준다. → 진짜 결과 파일로 바꿔도 같은 길을 지난다."""

    def __init__(self, world: SimWorld):
        self.world = world
        self.last_report: dict | None = None
        self.last_reason = ""

    def build_report(self) -> dict:
        w = self.world
        with w._lock:
            objs = []
            for r in sorted(w.items.values(), key=lambda r: r["slot"] if r["slot"] is not None else 99):
                if r["loc"] != LOC_BIN or r["slot"] is None:
                    continue
                x, y = SLOTS_MM[r["slot"]]
                cx, cy = mm_to_px(x, y)
                q = r.get("qwen")
                if q and w.faults.get("blur"):         # 흐린 촬영: 색·글자·스티커를 못 읽음(품목·모양은 읽음)
                    q = {**q, "colors": [], "logos_or_text": [], "sticker_status": "unknown", "stickers": []}
                objs.append({"id": len(objs), "class_name": "object", "confidence": 0.88,
                             "bbox": [cx - 50, cy - 34, cx + 50, cy + 34], "center_px": [cx, cy],
                             "center_world_mm": [x, y], "calibration_valid": not w.faults["calib_fail"],
                             "qwen": {"status": "ok", "features": copy.deepcopy(q)} if q else
                             {"status": "failed", "features": None}, "sim_item_id": r["item_id"]})
            calib = ({"valid": False} if w.faults["calib_fail"] else
                     {"valid": True, "correspondence_count": 8, "max_reprojection_error_mm": 0.6})
            return {"captured_at": _now_iso(), "sequence": {"status": "complete" if objs else "no_detections"},
                    "objects": objs, "calibration": calib, "simulated": True}

    def vision_topview(self) -> list[dict]:
        self.world.arm["phase"] = "탑뷰 촬영"
        self.world._touch()
        self.world.sleep(1.2)
        report = self.build_report()
        self.last_report = report
        dets = adapt_report(report)
        by_vid = {o["id"]: o["sim_item_id"] for o in report["objects"]}
        for d in dets:                       # 화면·시험 확인용 정답 표시(흐름은 쓰지 않음)
            d["object_id"] = by_vid.get(d.get("vision_id"))
        self.last_reason = "" if report["calibration"].get("valid") else "보정 없음(가상 #보정실패) — 로봇은 움직이지 않음"
        if self.world.faults["calib_fail"]:
            self.world.faults["calib_fail"] = False          # 한 번만
        self.world.faults["blur"] = False                    # 흐린 촬영도 한 번만(다시 찍으면 제대로 보임)
        self.world.arm["phase"] = "대기"
        self.world._touch()
        return dets


# ---------- 가상 로봇팔 ----------
class SimRobot:
    """작업대 mm 좌표로 움직이는 가상 SO-101 팔로워. 움직이는 동안 세계의 팔 위치·높이·관절 6개를 조금씩 바꿔 화면에서 보인다.
    정지 버튼(robot_stop)은 다른 스레드에서 와도 움직임 중간에 바로 멈춘다(진짜 로봇의 즉시 정지 흉내).
    바구니에 내려놓으면 결과(성공)를 먼저 돌려주고, 원점 복귀는 뒤에서 한다(화면의 '바구니 전달' 단계가 늦게 켜지지 않게)."""

    STEPS = 12

    def __init__(self, world: SimWorld):
        self.world = world

    def _pose(self, **kw) -> None:
        arm = self.world.arm
        arm.update(kw)
        arm["joints"] = so101_joints(arm["x"], arm["y"], arm["z"], arm["gripper"])
        self.world._touch()

    def _move(self, x=None, y=None, z=None, grip=None, seconds: float = 1.0, phase: str | None = None) -> bool:
        w, arm = self.world, self.world.arm
        if phase:
            arm["phase"] = phase
        start = {k: arm[k] for k in ("x", "y", "z", "gripper")}
        goal = {"x": start["x"] if x is None else float(x), "y": start["y"] if y is None else float(y),
                "z": start["z"] if z is None else float(z), "gripper": start["gripper"] if grip is None else float(grip)}
        for i in range(1, self.STEPS + 1):
            if arm["stopped"]:
                return False
            t = i / self.STEPS
            t = t * t * (3 - 2 * t)                      # 부드럽게 출발·도착
            self._pose(**{k: round(start[k] + (goal[k] - start[k]) * t, 1) for k in goal})
            w.sleep(seconds / self.STEPS)
        return not arm["stopped"]

    def _wait_homing(self) -> None:
        t = self.world.homing
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join()

    def _blocked(self) -> dict | None:
        if self.world.arm["stopped"]:
            return robot_result(False, f"{STAFF_STOP_REASON} — 로봇 정지 상태(직원 확인 후 원점 복귀)")
        return None

    def robot_approach(self, center_mm, center_px) -> dict:
        self._wait_homing()
        if (b := self._blocked()):
            return b
        x, y = float(center_mm[0]), float(center_mm[1])
        if not (BIN_MM[0] - 20 <= x <= BIN_MM[2] + 20 and BIN_MM[1] - 20 <= y <= BIN_MM[3] + 20):
            return robot_result(False, f"작업대 밖 좌표({x:.0f}, {y:.0f})mm")
        self.world.arm["target"] = self.world.item_at(x, y)
        if not self._move(x, y, HOVER_Z, 70, 2.2, "사전 접근(물건 위)"):
            return robot_result(False, STAFF_STOP_REASON)
        self._pose(phase="접근 완료 · 집게 열림")
        return robot_result(True)

    def robot_grasp(self) -> dict:
        if (b := self._blocked()):
            return b
        w, arm = self.world, self.world.arm
        if not self._move(z=PICK_Z, seconds=0.8, phase="집는 중(VLA) · 내려감"):
            return robot_result(False, STAFF_STOP_REASON)
        if not self._move(grip=8, seconds=0.5, phase="집는 중(VLA) · 집게 닫음"):
            return robot_result(False, STAFF_STOP_REASON)
        with w._lock:
            fail = None
            if w.faults["grasp_fail"] > 0:
                w.faults["grasp_fail"] -= 1
                fail = "가상: 물건이 미끄러짐"
            target = arm.get("target")
            if not fail and (not target or w.items.get(target, {}).get("loc") != LOC_BIN):
                fail = "그 자리에 물건이 없음"
            if not fail:
                w.move(target, LOC_GRIPPER)
                arm["holding"] = target
        if fail:                                          # 빈 집게를 다시 열고 들어 올림
            self._move(z=HOVER_Z, grip=70, seconds=0.6, phase="집기 실패")
            return robot_result(False, fail)
        if not self._move(z=HOVER_Z, seconds=0.6, phase="들어 올림"):
            return robot_result(False, STAFF_STOP_REASON)
        return robot_result(True)

    def robot_verify_grasp(self) -> dict:
        self.world.sleep(0.5)
        return robot_result(bool(self.world.arm.get("holding")), "그리퍼가 비어 있음")

    def robot_deliver(self) -> dict:
        if (b := self._blocked()):
            return b
        w, arm = self.world, self.world.arm
        if not self._move(BASKET_MM[0], BASKET_MM[1], HOVER_Z, None, 2.4, "제출보관함으로 이동"):
            return robot_result(False, STAFF_STOP_REASON)
        if not self._move(z=DROP_Z, seconds=0.4, phase="제출보관함 위로 내림"):
            return robot_result(False, STAFF_STOP_REASON)
        if not self._move(grip=70, seconds=0.4, phase="집게 열어 내려놓음"):
            return robot_result(False, STAFF_STOP_REASON)
        with w._lock:
            held = arm.get("holding")
            if held:
                w.move(held, LOC_BASKET)
            arm["holding"], arm["target"] = None, None
        self._pose(phase="제출보관함에 내려놓음")

        def go_home():
            w.sleep(0.4)
            if self._move(HOME_MM[0], HOME_MM[1], HOME_Z, HOME_GRIP, 1.6, "원점으로"):
                self._pose(phase="대기")
        w.homing = threading.Thread(target=go_home, daemon=True)
        w.homing.start()
        return robot_result(True)

    def robot_stop(self) -> dict:
        self.world.arm["stopped"] = True
        self._pose(phase="정지")
        return robot_result(True)

    def robot_home(self) -> dict:
        w, arm = self.world, self.world.arm
        self._wait_homing()
        arm["stopped"] = False
        held = arm.get("holding")
        if held:                                    # 들고 있던 물건은 직원이 받아 따로 보관(가상)
            w.move(held, LOC_STAFF)
            arm["holding"] = None
        arm["target"] = None
        self._move(z=HOVER_Z + 40, grip=HOME_GRIP, seconds=0.6, phase="원점 복귀 · 들어 올림")
        self._move(HOME_MM[0], HOME_MM[1], HOME_Z, HOME_GRIP, 1.6, "원점 복귀")
        self._pose(phase="대기")
        return robot_result(True)

    def robot_state(self) -> dict:
        """지금 상태(docs/contracts/robot_api.md 의 robot_state 모양). 화면 /robot/state 가 읽는다"""
        arm = self.world.arm
        return {"phase": arm["phase"], "stopped": bool(arm["stopped"]), "holding": arm.get("holding"),
                "joints": {k: float(v) for k, v in (arm.get("joints") or {}).items()}, "source": "sim"}


__all__ = ["SLOT_IDS", "slot_rows", "SO101_JOINTS", "SO101_LIMITS", "ARM_SCALE", "so101_joints", "SEED_ITEMS", "SimWorld", "SimTopview", "SimRobot", "sim_qwen", "query_features", "parse_place", "split_tags",
           "lost_station", "mm_to_px", "STATIONS", "LOC_KIOSK", "LOC_TRANSIT", "LOC_BIN", "LOC_BASKET", "NONE"]
