"""LF-5: text/transcript/photo observations -> reviewed search handoff.

No claim creation, identity verification, reservation or automatic search is done here.
"""
import re
import copy
import secrets
import threading
import time
from datetime import datetime, date, timedelta, timezone
from agents.contracts import (CATEGORIES, DESCRIPTION_FIELDS, UNKNOWN, inactive_category_message, is_active_category,
                              mentions_phone, without_non_phone)
from agents.support_security import normalized_text, has_private_pattern

KST = timezone(timedelta(hours=9))
ALIASES = {"지갑": ("지갑", "wallet", "카드 케이스", "카드케이스", "카드홀더", "카드 홀더"), "USB": ("usb", "유에스비", "유에스비 메모리"),
           "모형폰": ("휴대폰", "휴대전화", "스마트폰", "모형폰", "핸드폰", "전화기", "아이폰", "갤럭시", "폰"),  # 11/9 맨 '폰'은 mentions_phone(이어폰·헤드폰 제외)
           "립밤": ("립밤",), "핸드크림": ("핸드크림", "핸드 크림"), "보조배터리": ("보조배터리", "보조 배터리", "배터리", "밧데리", "빳데리", "보배")}   # 11/9 채점표: '밧데리·보배·화이트 배터리' 도 보조배터리
# 11/6: 비전(agents/vision_adapter.py COLOR)과 같은 묶음으로 — light blue→파랑, beige→갈색, purple·orange→기타
COLORS = {"검정": ("검정", "검은", "검정색", "블랙", "까만"), "흰색": ("흰색", "하얀", "화이트", "흰 ", "흰것", "흰거"),
          "회색": ("회색", "은색", "실버", "그레이"), "빨강": ("빨간", "빨강", "레드"),
          "파랑": ("파란", "파랑", "하늘색", "블루"), "남색": ("남색", "네이비", "곤색"),
          "갈색": ("갈색", "브라운", "베이지"), "초록": ("초록", "녹색", "연두", "그린"),
          "노랑": ("노란", "노랑", "옐로"), "분홍": ("분홍", "핑크")}
# 우리 색 목록(contracts.COLORS) 밖의 색 → "기타"로 찾는다(비전도 purple·orange 등은 기타). 연보라·진보라도 보라. "자주"는 "자주 잃어버려요"와 헷갈려 뺌
OTHER_COLORS = ("보라", "퍼플", "라벤더", "주황", "오렌지", "금색", "골드", "민트", "청록", "카키", "와인색", "버건디")


def checked_text(value, name="설명", limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name}은 1~{limit}자로 입력하세요")
    value = normalized_text(value)
    if not value or len(value) > limit:
        raise ValueError(f"{name}은 1~{limit}자로 입력하세요")
    if has_private_pattern(value):
        raise ValueError("설명에서 이름·연락처·신분번호 등 개인정보를 제외해주세요")
    return value.strip()


# 11/9 채점표: "아니 파란색이요", "지갑 말고 보조배터리요" — 고쳐 말한 뒤쪽이 진짜 조건
CORRECTION = re.compile(r"말고|아니(?:요|고|라|야|다)?(?=[\s,.!?]|$)|잘못\s*말했\S*")


def correction_tail(text):
    """고쳐 말한 문장의 뒤쪽(새 조건). 고쳐 말하기가 없거나 뒤가 비면 None"""
    hits = list(CORRECTION.finditer(text))
    if not hits:
        return None
    tail = text[hits[-1].end():].strip(" ,.!?")
    return tail or None


def text_features(text, corrected=False):
    """corrected=True(챗봇 대화): "X 말고 Y"의 Y를 씀. 기본(설명 입력란)은 예전처럼 부정이 있으면 추측하지 않음"""
    text = checked_text(text).lower()
    desc, warnings = {}, []
    tail = correction_tail(text) if corrected else None
    for field, aliases in (("category", ALIASES), ("color", COLORS)):
        def present(term):
            # '검은색' and '밝은색' contain '은색' but do not mean silver.
            return bool(re.search(r"(?<![가-힣])은색", text)) if term == "은색" else term in text
        if field == "category":       # 11/9 '이어폰·헤드폰·에어팟'은 휴대폰이 아님 → 그 말을 지운 글에서 품목을 찾고, '폰'은 공용 규칙으로
            found = {label for label, terms in aliases.items() if label != "모형폰"
                     and any(term in without_non_phone(text) for term in terms)} | ({"모형폰"} if mentions_phone(text) else set())
        else:
            found = {label for label, terms in aliases.items() if any(present(term) for term in terms)}
        if field == "color" and any(term in text for term in OTHER_COLORS):
            found.add("기타")                  # 11/6 연보라색 → 예전엔 색을 못 알아듣고 색 없이(다른 색 후보까지) 찾았음
        if tail and found:                     # 고쳐 말하기: 뒤쪽에 이 칸 값이 하나 있으면 그것만 씀(앞쪽은 버린 조건)
            in_tail = {label for label in found if any(
                (bool(re.search(r"(?<![가-힣])은색", tail)) if t == "은색" else t in tail) for t in (OTHER_COLORS if label == '기타' else aliases[label]))}
            if field == "category" and "모형폰" in found:
                in_tail = (in_tail - {"모형폰"}) | ({"모형폰"} if mentions_phone(tail) else set())
            if len(in_tail) == 1:
                desc[field] = in_tail.pop()
                continue
        if len(found) == 1 and not re.search(r"아니|말고|않|제외", text):
            desc[field] = found.pop()
        elif found:
            label = "품목" if field == "category" else "색상"
            warnings.append(f"{label}을 하나로 정하기 어렵습니다. 아래 내용을 직접 확인해주세요")
    desc.setdefault("category", UNKNOWN)
    shapes = [s for s in ("반지갑", "장지갑", "직사각형", "원통형", "원형") if s in text]
    if len(shapes) == 1:
        desc["shape"] = shapes[0]
    # Only explicitly supplied attributes; never infer material from a wallet category.
    materials = [s for s in ("가죽", "플라스틱", "금속", "천")
                 if (bool(re.search(r"(?<![가-힣])천(?=\s|재질|소재|으로|$)", text)) if s == "천" else s in text)]
    if len(materials) == 1 and not re.search(r"아니|말고|않|제외", text):
        desc["material"] = materials[0]
    marks = re.findall(r"(?:별|하트|원|네모)(?:\s*모양)?\s*스티커|(?:(?:햄스터|고양이|강아지|곰|토끼|캐릭터)(?:\s*모양)?\s*)?(?:키링|열쇠고리)", text)
    if marks and not re.search(r"아니|말고|않|제외|없", text):
        desc["mark"] = ", ".join(dict.fromkeys(marks))
    elif marks:
        warnings.append("부속품·표시의 유무를 특징 칸에서 직접 확인해주세요")
    return desc, warnings


def location(payload, text="", today=None):
    today = today or datetime.now(KST).date()
    result = {}
    raw = payload.get("lost_date")
    if not raw:
        dates = set(re.findall(r"\d{4}-\d{2}-\d{2}", text))
        relative = [x for x in ("오늘", "어제") if x in text]
        if len(dates) + len(relative) == 1:
            raw = next(iter(dates)) if dates else (today - timedelta(days=int(relative == ["어제"]))).isoformat()
    if raw:
        try:
            day = date.fromisoformat(raw)
        except (TypeError, ValueError):
            raise ValueError("분실 날짜는 YYYY-MM-DD로 입력하세요") from None
        if day > today:
            raise ValueError("분실 날짜가 미래일 수 없습니다")
        result["lost_date"] = day.isoformat()
    for key, pattern, limit in (("lost_line", r"\d{1,2}호선", 16), ("lost_station", r"[가-힣A-Za-z]{1,24}역", 32)):
        value = payload.get(key)
        if not value:
            matches = set(re.findall(pattern, text))
            value = next(iter(matches)) if len(matches) == 1 else None
        if value:
            result[key] = checked_text(value, key, limit)
    return result


def validate_description(desc):
    if not isinstance(desc, dict) or set(desc) - set(DESCRIPTION_FIELDS):
        raise ValueError("설명에는 팀 공통 특징 항목만 사용할 수 있습니다")
    result = {k: checked_text(v, k, 200) for k, v in desc.items()}
    if result.get("category") not in [*CATEGORIES, UNKNOWN]:
        raise ValueError("지원하지 않는 품목입니다")
    from agents.contracts import COLORS as VALID_COLORS
    if result.get('color') not in (None, UNKNOWN, *VALID_COLORS):
        raise ValueError("색상은 검정·흰색·파랑 등 지원하는 색으로 선택해주세요. 모르면 비워주세요")
    if result.get('color') == UNKNOWN:
        result.pop('color')
    return result


class DescriptionService:
    def __init__(self, photo_extractor=None, transcriber=None, ttl=1800, max_pending=100):
        self.photo_extractor = photo_extractor
        self.transcriber = transcriber
        self.ttl, self.max_pending = ttl, max_pending
        self._pending, self._lock = {}, threading.Lock()

    def _save(self, description, metadata, warnings, source):
        description = validate_description(description)
        cat = description.get("category")
        if cat not in (None, UNKNOWN) and not is_active_category(cat):
            # 11/9 운영하지 않는 품목(립밤): 알아들었다고 안내하고 품목은 '확인 불가'로 → 사용자가 다시 고르기 전에는 검색으로 넘기지 않음
            description = {**description, "category": UNKNOWN}
            warnings = [inactive_category_message(cat)] + list(warnings)
        token = secrets.token_urlsafe(24)
        proposal = {"proposal_id": token, "description": description, **metadata,
                    "warnings": warnings, "source": source, "requires_confirmation": True,
                    "missing_fields": [k for k in ("lost_date", "lost_line", "lost_station") if not metadata.get(k)]}
        with self._lock:
            now = time.monotonic()
            self._pending = {k: v for k, v in self._pending.items() if now - v[0] < self.ttl}
            if len(self._pending) >= self.max_pending:
                raise RuntimeError("현재 요청이 많습니다. 잠시 후 다시 시도해주세요")
            self._pending[token] = (now, copy.deepcopy(proposal))
        return proposal

    def from_text(self, payload):
        text = checked_text(payload.get("text"))
        desc, warnings = text_features(text, corrected=True)
        return self._save(desc, location(payload, text), warnings, "user_text")

    def from_photo(self, photo_bytes, metadata):
        meta = location(metadata)
        if self.photo_extractor is None:
            raise RuntimeError("사진 분석 연결이 설정되지 않았습니다. 글로 설명하거나 잠시 후 다시 시도해주세요")
        # Extractor is a server-owned adapter, never caller-supplied feature JSON.
        try:
            desc = self.photo_extractor(photo_bytes)
        except (OSError, RuntimeError):
            raise RuntimeError("사진 분석을 완료하지 못했습니다. 글로 설명하거나 잠시 후 다시 시도해주세요") from None
        return self._save(desc, meta, ["사진의 품목·색상을 직접 확인해주세요. 재질·문자·손상은 분석하지 않습니다"], "photo_model")

    def transcribe_audio(self, audio_path, limit=2000):
        if self.transcriber is None:
            raise RuntimeError("음성 인식 모델이 준비되지 않았습니다. 글자로 입력할 수 있습니다")
        # Existing speech module owns loading/closing GPU resources.
        try:
            with self.transcriber() as worker:
                transcript = worker.transcribe(audio_path)
        except (ImportError, OSError, RuntimeError):
            raise RuntimeError("음성 모델·라이브러리 연결을 확인해주세요. 글자로 입력할 수 있습니다") from None
        if not isinstance(transcript, dict):
            raise RuntimeError("음성 인식 응답을 확인할 수 없습니다. 다시 녹음하거나 글자로 입력해주세요")
        if transcript.get("status") != "transcribed":
            raise ValueError("음성을 인식하지 못했습니다. 다시 녹음하거나 글자로 입력해주세요")
        return checked_text(transcript.get("text"), '인식된 말', limit)

    def from_audio(self, audio_path, metadata):
        location(metadata)  # Reject invalid metadata before costly model inference.
        text = self.transcribe_audio(audio_path)
        desc, warnings = text_features(text, corrected=True)
        result = self._save(desc, location(metadata, text), warnings + ["음성 인식 문장을 확인해주세요"], "speech")
        # Returned for user review, but not retained in the proposal store or search handoff.
        return {**result, "transcript": text}

    def confirm(self, token, payload):
        if payload.get("confirmed") is not True:
            raise ValueError("설명 확인에 동의해야 검색용으로 전달됩니다")
        with self._lock:
            entry = self._pending.get(token)
            if not entry or time.monotonic() - entry[0] >= self.ttl:
                raise ValueError("설명 확인 시간이 지났습니다. 다시 입력해주세요")
            proposal = entry[1]
        desc = validate_description(payload.get("description", proposal["description"]))
        if desc.get("category") not in (None, UNKNOWN) and not is_active_category(desc["category"]):
            raise ValueError(inactive_category_message(desc["category"]))       # 11/9 운영하지 않는 품목은 검색으로 넘기지 않음
        meta = location({k: payload.get(k, proposal.get(k)) for k in ("lost_date", "lost_line", "lost_station")})
        missing = [k for k in ("lost_date", "lost_line", "lost_station") if not meta.get(k)]
        if desc.get("category") in (None, UNKNOWN):
            missing.append("category")
        if missing:
            raise ValueError("추가 입력 필요: " + ", ".join(missing))
        if not re.fullmatch(r'[1-9][0-9]?호선', meta['lost_line']):
            raise ValueError("호선은 1호선처럼 입력해주세요")
        # This is a handoff only. Downstream search must apply its own consent/identity gates.
        from agents.lost_search import matching_query
        return {"status": "ready_for_search", "description": desc, **meta,
                "matching_query": matching_query(desc),
                "user_confirmed": True, "identity_verified": False,
                "notice": "본인 인증·필수 동의·후보 검색·예약은 기존 웹 절차에서 별도로 진행합니다"}


def build_description_graph(service):
    from typing import TypedDict
    from langgraph.graph import StateGraph, START, END
    class State(TypedDict, total=False):
        payload: dict
        proposal: dict
        description: dict
        warnings: list
        metadata: dict
    def extract(state):
        desc, warnings = text_features(state["payload"].get("text"), corrected=True)
        return {"description": desc, "warnings": warnings}
    def context(state):
        return {"metadata": location(state["payload"], state["payload"]["text"])}
    def review(state):
        return {"proposal": service._save(state["description"], state["metadata"], state["warnings"], "user_text")}
    graph = StateGraph(State)
    graph.add_node("extract_explicit_features", extract)
    graph.add_node("collect_loss_context", context)
    graph.add_node("prepare_user_review", review)
    graph.add_edge(START, "extract_explicit_features")
    graph.add_edge("extract_explicit_features", "collect_loss_context")
    graph.add_edge("collect_loss_context", "prepare_user_review")
    graph.add_edge("prepare_user_review", END)
    return graph.compile()
