"""비전 공용 설정: 품목 이름, 파일 이름 규칙.

한줄 설명: 촬영·라벨링·학습이 같은 품목 번호와 파일 이름을 쓰도록 한곳에 모아 둔 규칙.
"""
from __future__ import annotations

import re

# YOLO 클래스 번호 순서. 한 번 정하면 바꾸지 않는다(바꾸면 기존 라벨이 모두 틀어짐).
# 11/6 6종 고정(LF-3): 0~3번은 예전 4종(wallet·usb·lipbalm·phone) 순서 그대로 → 기존 라벨 번호를 다시 쓸 수 있다.
# 이름은 Qwen(vision/item_features.py)·변환(agents/vision_adapter.py)·매칭(matching/)과 같은 표기. 한국어는 agents/contracts.py CATEGORIES
CLASSES = ["card_wallet", "usb", "lip_balm", "phone", "hand_cream", "power_bank"]
CLASS_KO = {"card_wallet": "지갑", "usb": "USB", "lip_balm": "립밤", "phone": "모형폰",
            "hand_cream": "핸드크림", "power_bank": "보조배터리"}
# 예전 이름 → 새 이름. 이미 찍은 사진 파일 이름과 라벨 도구 classes.txt 의 예전 이름을 그대로 읽기 위한 것(새로 찍을 때는 새 이름만)
LEGACY_CLASS_ALIASES = {"wallet": "card_wallet", "lipbalm": "lip_balm"}


def canonical_class(name: str) -> str | None:
    """예전 이름이면 새 이름으로, 6종이 아니면 None."""
    name = LEGACY_CLASS_ALIASES.get(name, name)
    return name if name in CLASSES else None


# 물건 ID: 영문 대문자 1자 + 숫자 2자리 (예: W01 지갑1, U02 USB2, L01 립밤1, P01 모형폰1, H01 핸드크림1, B01 보조배터리1)
OBJECT_ID_RE = re.compile(r"^[A-Z]\d{2}$")
# 세션: s + 숫자 (예: s1, s2) — 촬영한 날·시간대가 다르면 세션을 바꾼다
SESSION_RE = re.compile(r"^s\d{1,2}$")
# 파일 이름: 품목_물건ID_세션_번호.jpg (예: card_wallet_W01_s1_012.jpg, 예전 사진 wallet_W01_s1_012.jpg 도 읽음)
# 품목 이름에 밑줄이 들어가므로(lip_balm) 소문자 묶음을 밑줄로 이어 받는다. 물건 ID 는 대문자로 시작해 경계가 겹치지 않음
FILENAME_RE = re.compile(r"^(?P<cat>[a-z]+(?:_[a-z]+)*)_(?P<obj>[A-Z]\d{2})_(?P<ses>s\d{1,2})_(?P<idx>\d{3,})\.jpg$")


def validate_names(category: str, object_id: str, session: str) -> None:
    if category not in CLASSES:
        raise ValueError(f"품목은 {CLASSES} 중 하나여야 합니다: {category!r}")
    if not OBJECT_ID_RE.match(object_id):
        raise ValueError(f"물건 ID 형식이 아닙니다(예: W01): {object_id!r}")
    if not SESSION_RE.match(session):
        raise ValueError(f"세션 형식이 아닙니다(예: s1): {session!r}")


def make_filename(category: str, object_id: str, session: str, index: int) -> str:
    validate_names(category, object_id, session)
    if index < 0:
        raise ValueError("번호는 0 이상이어야 합니다")
    return f"{category}_{object_id}_{session}_{index:03d}.jpg"


def parse_filename(name: str) -> dict | None:
    m = FILENAME_RE.match(name)
    category = canonical_class(m.group("cat")) if m else None
    if category is None:
        return None
    return {"category": category, "object_id": m.group("obj"), "session": m.group("ses"), "index": int(m.group("idx"))}
