"""비전 공용 설정: 품목 이름, 파일 이름 규칙.

한줄 설명: 촬영·라벨링·학습이 같은 품목 번호와 파일 이름을 쓰도록 한곳에 모아 둔 규칙.
"""
from __future__ import annotations

import re

# YOLO 클래스 번호 순서. 한 번 정하면 바꾸지 않는다(바꾸면 기존 라벨이 모두 틀어짐).
CLASSES = ["wallet", "usb", "lipbalm", "phone"]
CLASS_KO = {"wallet": "지갑", "usb": "USB", "lipbalm": "립밤", "phone": "모형폰"}

# 물건 ID: 영문 대문자 1자 + 숫자 2자리 (예: W01 지갑1, U02 USB2, L01 립밤1, P01 모형폰1)
OBJECT_ID_RE = re.compile(r"^[A-Z]\d{2}$")
# 세션: s + 숫자 (예: s1, s2) — 촬영한 날·시간대가 다르면 세션을 바꾼다
SESSION_RE = re.compile(r"^s\d{1,2}$")
# 파일 이름: 품목_물건ID_세션_번호.jpg (예: wallet_W01_s1_012.jpg)
FILENAME_RE = re.compile(r"^(?P<cat>[a-z]+)_(?P<obj>[A-Z]\d{2})_(?P<ses>s\d{1,2})_(?P<idx>\d{3,})\.jpg$")


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
    if not m or m.group("cat") not in CLASSES:
        return None
    return {"category": m.group("cat"), "object_id": m.group("obj"), "session": m.group("ses"), "index": int(m.group("idx"))}
