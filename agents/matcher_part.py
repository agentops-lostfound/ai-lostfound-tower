"""매칭 부품 연결 — 김건태 matching/policy.py(LF-3·LF-20)를 관제탑 match_item 약속으로 감싼다.

한줄 설명: 관제탑의 한국어 계약 특징(지갑·검정·"star sticker")을 건태님 정책이 읽는 영어 조건으로 바꿔 판정을 받고,
그 결과(matched / needs_confirmation / no_match)를 관제탑 약속(matched / uncertain / none + index)으로 돌려준다.

켜는 법: .env 에 TOWER_MATCHER=policy (기본은 기존 단순 비교 그대로) — docs/design/swap_guide.md 3장
- 색은 관제탑 변환기(vision_adapter)가 이미 꾸밈말을 떼고 기본 색으로 맞춘 값(dark red → 빨강)을 넘긴다
  → 건태님 표에 없는 "dark red" 같은 값이 '색 불일치'로 제외되는 문제를 관제탑 쪽에서 피한다
- '기타'·'확인 불가' 색은 조건으로 쓰지 않는다(모르는 것을 불일치로 보지 않음)
- 자유 특징(스티커 설명·글자)은 지금은 낱말 겹침 점수(자리표시)로 비교한다. MiniLM 임베딩은 PC 에서 연결(TBD)
- 정책이 예외를 내면 약속대로 none(→ 직원 확인)을 돌려준다
"""
from __future__ import annotations

import re

from agents.contracts import MATCH_NONE, MATCH_OK, MATCH_UNCERTAIN, NONE, UNKNOWN

CATEGORY_EN = {"지갑": "card_wallet", "USB": "usb", "립밤": "lip_balm", "모형폰": "phone",
               "핸드크림": "hand_cream", "보조배터리": "power_bank"}
COLOR_EN = {"검정": "black", "흰색": "white", "회색": "gray", "빨강": "red", "파랑": "blue", "남색": "navy",
            "초록": "green", "노랑": "yellow", "갈색": "brown"}
STATUS = {"matched": MATCH_OK, "needs_confirmation": MATCH_UNCERTAIN, "no_match": MATCH_NONE}


def _known(v) -> bool:
    return isinstance(v, str) and v.strip() not in ("", UNKNOWN, NONE)


def to_policy_features(f: dict) -> dict:
    """관제탑 계약 특징 → 건태님 정책 입력(category·colors·sticker_status)."""
    f = f or {}
    mark = f.get("mark")
    sticker = "absent" if mark == NONE else ("present" if _known(mark) else "unknown")
    color = COLOR_EN.get(f.get("color"))
    return {"category": CATEGORY_EN.get(f.get("category"), "unknown"),
            "colors": [color] if color else [], "sticker_status": sticker}


def free_text(f: dict) -> str:
    """확인 질문에 쓰는 비공개 특징(스티커 설명·보이는 글자)만 모은 문장."""
    return " ".join(str(f.get(k)) for k in ("mark", "visible_text") if _known((f or {}).get(k)))


def word_overlap(a: str, b: str) -> float:
    """자리표시 의미 점수: 낱말 겹침(자카드). 임베딩이 붙으면 바뀐다."""
    wa, wb = (set(re.findall(r"[0-9a-z가-힣]+", s.lower())) for s in (a, b))
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


class PolicyMatcherPart:
    """CompositeBackend(matcher=...) 에 꽂는 매칭 부품."""

    def __init__(self, config: dict | None = None, semantic=word_overlap):
        from matching.policy import load_config
        self.config = config or load_config()
        self.semantic = semantic
        self.last_decision: dict = {}

    def match_item(self, query: dict, detections: list[dict]) -> dict:
        try:
            from matching.policy import apply_policy
            q = to_policy_features(query)
            qtext = free_text(query)
            cands = []
            for i, d in enumerate(detections):
                f = d.get("features") or {}
                ctext = free_text(f)
                cos = self.semantic(qtext, ctext) if qtext and ctext else None
                cands.append({"id": i, "features": to_policy_features(f), "cosine_similarity": cos})
            ranking, decision = apply_policy(cands, q, self.config)
        except Exception as e:      # 약속: 예외 대신 none → 흐름이 직원 확인으로
            self.last_decision = {"error": type(e).__name__}
            return {"status": MATCH_NONE, "index": None, "score": 0.0, "margin": 0.0, "ranking": []}
        self.last_decision = decision
        status = STATUS.get(decision.get("status"), MATCH_NONE)
        top = decision.get("top_candidate_id")
        top_score = next((r["final_score"] for r in ranking if r["id"] == top), 0.0)
        margin = decision.get("margin")
        return {"status": status,
                "index": decision.get("selected_id") if status == MATCH_OK else top,
                "score": round(float(top_score), 3),
                "margin": round(float(margin), 3) if margin is not None else 1.0,
                "ranking": [r["id"] for r in ranking],
                "reasons": decision.get("reasons") or ([decision["reason"]] if decision.get("reason") else [])}


def matcher_part_from_env(env: dict | None = None):
    """TOWER_MATCHER=policy 면 PolicyMatcherPart, 아니면 None(기존 단순 비교 유지)."""
    import os
    env = os.environ if env is None else env
    return PolicyMatcherPart() if str(env.get("TOWER_MATCHER") or "").strip().lower() == "policy" else None


__all__ = ["PolicyMatcherPart", "matcher_part_from_env", "to_policy_features", "free_text", "word_overlap"]
