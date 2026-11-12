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

# 계약 품목 6종(11/3 핸드크림·보조배터리 정식 추가) + 없음. 물건 ID 앞글자: W 지갑 · U USB · L 립밤 · P 모형폰 · H 핸드크림 · B 보조배터리
# 11/9: 립밤은 운영 품목에서 뺐지만 계약 목록에는 남긴다 — 옛 기록(DB item.category)·비전 클래스(lip_balm)·물건 ID 접두 L 이
#       이 목록으로 검사되므로, 빼면 이미 들어온 립밤 기록과 Qwen 결과가 '목록에 없는 값'으로 거절된다
CATEGORIES = ["지갑", "USB", "립밤", "모형폰", "핸드크림", "보조배터리", "없음"]
# 운영 품목(11/9 사용자 결정): 지금 접수·찾기·보관 칸에서 실제로 다루는 품목. **품목을 더 빼거나 넣을 때는 이 한 줄만 고친다**
#   → 보관함 정답지(agents/storage.py)·챗봇 안내·가상 시연 문구가 이 목록을 따른다(화면 HTML 은 상수를 따로 둠: 아래 주석)
#   립밤 제외 이유: YOLO 탑뷰 모델이 립밤을 잘 찾지 못함(vision/DETECTION_STATUS.md)
#   화면 쪽 같은 목록: web/kiosk/index.html CATS · web/lost/index.html 품목 칩 · web/lost-input/index.html 품목 선택
# 11/9 10:06 사용자 결정: 품목 4종 고정 — 목업폰 · 보조배터리 · 핸드크림 · 카드지갑(USB 도 뺌)
# 11/11 사용자 결정: 카드지갑은 포토박스 탑뷰가 잘 못 알아봐서 빼고 립밤을 다시 넣음 → 목업폰 · 보조배터리 · 핸드크림 · 립밤
ACTIVE_CATEGORIES = ["모형폰", "보조배터리", "핸드크림", "립밤"]   # 11/10 순서 = 보관함 열 순서(R1~R4) — 화면·챗봇이 같은 차례로 보여 줌
MVP_CATEGORIES = ACTIVE_CATEGORIES                  # 예전 이름(11/5 셀프서비스 MVP). 운영 품목과 같다
RETIRED_CATEGORIES = [c for c in CATEGORIES if c not in ACTIVE_CATEGORIES and c != "없음"]   # 계약에는 있지만 운영하지 않는 품목
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
# 11/4: 가상 시연용 초량역 등록기계 KIOSK-C 추가(디스코드 "초량역 ○번 출구에서 주웠어요" 시연, docs/design/virtual_demo.md)
#   앞글자는 C 가 아니라 S(Seomyeon): C 로 하면 접수 번호 C-20261104-0001 이 찾기 번호(C-날짜-순번)와 똑같아진다
MACHINE_LETTERS = {"KIOSK-A": "A", "KIOSK-C": "S", "CENTER": "H"}   # 11/11 중앙역 A · 초량역 S(앞글자는 11/4 서면역 때 정한 그대로 — 번호 체계 유지) · 본센터(부산역) 직접 접수 H (11/6 옛 KIOSK-B 중앙역은 삭제, 11/11 KIOSK-A 를 중앙역으로)

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


# 화면 표시용 한국어(저장 값은 Qwen 원문 그대로). 11/7: 직원 교차 검증 화면에 영어(rectangular · plastic)가 나와 공용으로 옮김
SHOW_KO = {"rectangular": "직사각형", "rectangle": "직사각형", "stick": "막대형", "cylinder": "원통형", "tube": "튜브형",
           "round": "원형", "square": "정사각형", "synthetic leather": "합성가죽", "leather": "가죽", "plastic": "플라스틱",
           "metal": "금속", "fabric": "천", "silicone": "실리콘", "paper": "종이", "rubber": "고무"}


def show_ko(v) -> str:
    """'rectangular, plastic' → '직사각형, 플라스틱'(모르는 말은 그대로). 품목 값도 화면 이름으로(모형폰 → 휴대폰)"""
    return ", ".join(category_label(SHOW_KO.get(x.strip().lower(), x.strip())) for x in str(v).split(","))


# 품목의 화면 이름(11/8). 저장·계약 값(CATEGORIES·DB·비전·매칭·API JSON)은 '모형폰' 그대로 두고,
# 사람에게 보이는 글(화면·디스코드·챗봇 문장)만 이 표를 거친다. 사용자 입력은 '모형폰'·'휴대폰' 둘 다 알아듣는다
# 11/10 사용자 결정: '지갑' 은 사람에게 '카드지갑' 으로 보인다(실물이 카드지갑). 값은 '지갑' 그대로(DB·계약·비전·매칭)
CATEGORY_LABEL = {"모형폰": "휴대폰", "지갑": "카드지갑"}


def category_label(cat) -> str:
    """품목 값 → 사람에게 보이는 이름('모형폰' → '휴대폰', 나머지·None 은 그대로 글자로)"""
    if cat is None:
        return ""
    return CATEGORY_LABEL.get(str(cat).strip(), str(cat))


def is_active_category(cat) -> bool:
    """지금 운영하는 품목인가(11/9). '휴대폰'처럼 화면 이름으로 와도 알아듣는다"""
    if cat is None:
        return False
    cat = str(cat).strip()
    return cat in ACTIVE_CATEGORIES or any(category_label(c) == cat for c in ACTIVE_CATEGORIES)


def active_category_text(sep: str = "·") -> str:
    """사람에게 보일 운영 품목 목록 글. 예: '지갑·휴대폰·핸드크림·보조배터리'"""
    return sep.join(category_label(c) for c in ACTIVE_CATEGORIES)


def inactive_category_message(cat) -> str:
    """운영하지 않는 품목 안내(11/9). 예: '립밤은 지금 운영하지 않는 품목이에요 — 지갑·휴대폰·핸드크림·보조배터리 4가지만 다뤄요'"""
    name = category_label(cat)
    last = name[-1:]
    josa = "은" if last and "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "는"
    return f"{name}{josa} 지금 운영하지 않는 품목이에요 — {active_category_text()} {len(ACTIVE_CATEGORIES)}가지만 다뤄요"


# 11/9 휴대폰 낱말(사용자 실측: "파란색 폰 잃어버렸어요. 초량역" → "무슨 물건인지 알 수 없어요").
# 한줄 설명: 사람들이 휴대폰을 부르는 여러 말을 한곳에 모아, 모든 입구(가상 시연·분실인 웹·챗봇·통계)가 똑같이 알아듣게 한다.
# - 앞말이 붙은 '폰'(이어폰·헤드폰)은 휴대폰이 아니다 → 휴대폰이 아닌 말을 먼저 지운 뒤, 앞에 한글이 붙지 않은 '폰'만 센다
# - '갤럭시 버즈'·'갤럭시 워치'도 휴대폰이 아님. 품목 값은 '모형폰' 그대로(화면 이름만 '휴대폰')
PHONE_WORDS = ("모형폰", "휴대폰", "핸드폰", "휴대전화", "스마트폰", "전화기", "아이폰", "갤럭시", "폰")
# 11/9: '새폰·내폰·폰케이스'도 휴대폰으로 — 앞말이 붙은 '폰'을 다 막지 않고, 휴대폰이 아닌 '…폰' 낱말만 먼저 지운다
NOT_PHONE_RE = re.compile(r"갤럭시\s*(?:버즈|워치|탭)|이어폰|헤드폰|에어폰|헤드셋|에어팟|버즈|메가폰|인터폰|색소폰|실로폰|마이크로?폰|스피커폰|확성기")
PHONE_RE = re.compile(r"모형폰|휴대폰|핸드폰|휴대\s*전화|스마트폰|전화기|아이폰|갤럭시|폰(?!트)")


def without_non_phone(text) -> str:
    """'이어폰·헤드폰·에어팟' 같은 휴대폰이 아닌 말을 빈칸으로 바꾼다(품목 낱말을 찾기 전에 쓴다)."""
    return NOT_PHONE_RE.sub(" ", str(text or "").lower())


def mentions_phone(text) -> bool:
    """글에 휴대폰을 뜻하는 말이 있는가. '파란색 폰'·'아이폰' → True, '이어폰'·'헤드폰'·'에어팟' → False"""
    return bool(PHONE_RE.search(without_non_phone(text)))


# 11/9 습득 역(사용자 요청: "각 물건이 어떤 역에서 습득한 건지 관제탑에서 보이게 해야 바로 검색이 가능할 듯").
# 물건 번호 앞글자 = 등록기계(MACHINE_LETTERS) → 사람이 읽는 역 이름. 화면(관제·보관함·직원)과 /live/state 가 함께 쓴다
MACHINE_STATION_NAME = {"KIOSK-A": "중앙역", "KIOSK-C": "초량역", "CENTER": "부산역 본센터"}
LETTER_STATION_NAME = {MACHINE_LETTERS[m]: name for m, name in MACHINE_STATION_NAME.items()}


def station_name(machine_id=None, item_id=None) -> str:
    """등록기계(없으면 물건 번호 앞글자) → 습득 역 이름. 모르면 빈 글자. 예: ('KIOSK-C') → '초량역', (None, 'A-…') → '중앙역'"""
    if machine_id in MACHINE_STATION_NAME:
        return MACHINE_STATION_NAME[machine_id]
    head = str(item_id or "")[:2]
    return LETTER_STATION_NAME.get(head[0], "") if len(head) == 2 and head[1] == "-" else ""


def public_card(features: dict) -> dict:
    """후보 카드에 보여도 되는 값만 남긴다(비공개 특징 제거)."""
    return {k: v for k, v in features.items() if k not in PRIVATE_FIELDS}


# 11/11 실물 시험: 아이폰 목업 뒤 사과 로고 — 분실인은 "사과"라고 답하고 Qwen 은 영어("apple logo")로 적어 확인 질문이 '글자 틀림'이 됐다.
# 로고·글자를 비교할 때 같은 뜻의 말을 한 묶음으로 본다(한국어·영어·흔한 별칭). 묶음 이름은 영어 소문자 — 저장 값은 바꾸지 않는다
LOGO_ALIASES = {
    "apple": ["apple", "애플", "사과"],          # '아이폰'·'갤럭시'는 넣지 않음 — 품목 이름이라 누구나 말할 수 있어 확인 질문이 쉬워짐
    "samsung": ["samsung", "삼성"],
    "lg": ["lg", "엘지"],
    "xiaomi": ["xiaomi", "샤오미", "mi"],
    "anker": ["anker", "앤커"],
    "vaseline": ["vaseline", "바세린"],        # 11/11 립밤(바세린 립테라피) — Qwen 은 영어 'Vaseline', 분실인은 '바세린'으로 씀
    "star": ["star", "별"],
    "heart": ["heart", "하트"],
}
_ALIAS_OF = {w: k for k, ws in LOGO_ALIASES.items() for w in ws}


def logo_tokens(text) -> set[str]:
    """로고·글자 비교용 낱말 묶음: 소문자 낱말 → 같은 뜻 묶음 이름(LOGO_ALIASES). 'logo'·'로고'·'sticker'·'스티커'·'글자'는 뺀다"""
    import re as _re
    words = set(_re.findall(r"[0-9a-z가-힣]+", str(text or "").lower()))
    words -= {"logo", "로고", "sticker", "스티커", "글자", "마크", "mark", "printed", "text"}
    out = set()
    for w in words:
        hit = _ALIAS_OF.get(w) or next((k for a, k in _ALIAS_OF.items() if len(a) >= 2 and not a.isascii() and w.startswith(a)), None)
        out.add(hit or w)                          # "사과로고"·"애플이요"처럼 조사가 붙어도 앞부분으로 찾는다
    return out
