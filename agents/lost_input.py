"""LF-5: text/transcript/photo observations -> reviewed search handoff.

No claim creation, identity verification, reservation or automatic search is done here.
"""
import re
import copy
import secrets
import threading
import time
from datetime import datetime, date, timedelta, timezone
from agents.contracts import CATEGORIES, DESCRIPTION_FIELDS, UNKNOWN
from agents.support_security import normalized_text, has_private_pattern

KST = timezone(timedelta(hours=9))
ALIASES = {"지갑": ("지갑", "wallet"), "USB": ("usb", "유에스비", "유에스비 메모리"),
           "모형폰": ("휴대폰", "휴대전화", "스마트폰", "모형폰", "핸드폰"),
           "립밤": ("립밤",), "핸드크림": ("핸드크림", "핸드 크림"), "보조배터리": ("보조배터리", "보조 배터리")}
COLORS = {"검정": ("검정", "검은", "검정색", "블랙"), "흰색": ("흰색", "하얀", "화이트"),
          "회색": ("회색", "은색", "실버"), "빨강": ("빨간", "빨강"), "파랑": ("파란", "파랑"),
          "남색": ("남색",), "갈색": ("갈색",), "초록": ("초록",), "노랑": ("노란", "노랑")}


def checked_text(value, name="설명", limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name}은 1~{limit}자로 입력하세요")
    value = normalized_text(value)
    if not value or len(value) > limit:
        raise ValueError(f"{name}은 1~{limit}자로 입력하세요")
    if has_private_pattern(value):
        raise ValueError("설명에서 이름·연락처·신분번호 등 개인정보를 제외해주세요")
    return value.strip()


def text_features(text):
    text = checked_text(text).lower()
    desc, warnings = {}, []
    for field, aliases in (("category", ALIASES), ("color", COLORS)):
        def present(term):
            # '검은색' and '밝은색' contain '은색' but do not mean silver.
            return bool(re.search(r"(?<![가-힣])은색", text)) if term == "은색" else term in text
        found = {label for label, terms in aliases.items() if any(present(term) for term in terms)}
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
    return result


class DescriptionService:
    def __init__(self, photo_extractor=None, transcriber=None, ttl=1800, max_pending=100):
        self.photo_extractor = photo_extractor
        self.transcriber = transcriber
        self.ttl, self.max_pending = ttl, max_pending
        self._pending, self._lock = {}, threading.Lock()

    def _save(self, description, metadata, warnings, source):
        description = validate_description(description)
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
        desc, warnings = text_features(text)
        return self._save(desc, location(payload, text), warnings, "user_text")

    def from_photo(self, photo_bytes, metadata):
        if self.photo_extractor is None:
            raise RuntimeError("사진 분석 연결이 설정되지 않았습니다")
        # Extractor is a server-owned adapter, never caller-supplied feature JSON.
        desc = self.photo_extractor(photo_bytes)
        return self._save(desc, location(metadata), ["사진의 품목·색상을 직접 확인해주세요. 재질·문자·손상은 분석하지 않습니다"], "photo_model")

    def transcribe_audio(self, audio_path, limit=2000):
        if self.transcriber is None:
            raise RuntimeError("음성 인식 모델이 준비되지 않았습니다. 글자로 입력할 수 있습니다")
        # Existing speech module owns loading/closing GPU resources.
        try:
            with self.transcriber() as worker:
                transcript = worker.transcribe(audio_path)
        except (ImportError, OSError, RuntimeError):
            raise RuntimeError("음성 모델·라이브러리 연결을 확인해주세요. 글자로 입력할 수 있습니다") from None
        if transcript.get("status") != "transcribed":
            raise ValueError("음성을 인식하지 못했습니다. 다시 녹음하거나 글자로 입력해주세요")
        return checked_text(transcript.get("text"), '인식된 말', limit)

    def from_audio(self, audio_path, metadata):
        text = self.transcribe_audio(audio_path)
        desc, warnings = text_features(text)
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
        meta = location({k: payload.get(k, proposal.get(k)) for k in ("lost_date", "lost_line", "lost_station")})
        missing = [k for k in ("lost_date", "lost_line", "lost_station") if not meta.get(k)]
        if desc.get("category") == UNKNOWN:
            missing.append("category")
        if missing:
            raise ValueError("추가 입력 필요: " + ", ".join(missing))
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
        desc, warnings = text_features(state["payload"].get("text"))
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
