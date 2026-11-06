"""챗봇 문서 검색(RAG 의 R) — LF-5 · 11/6 변재원

한줄 설명: 질문과 뜻이 가까운 안내 문단을 찾는다. 글자 2개씩 묶은 조각(문자 2-gram)으로 TF-IDF 점수를 매기는
가벼운 검색이라 추가 설치·GPU 가 필요 없다(띄어쓰기·조사가 달라도 "잃어버렸"·"분실" 같은 조각이 겹치면 찾음).

용어
- TF-IDF: 문단에 자주 나오면서(TF) 다른 문단에는 드문(IDF) 조각일수록 점수를 크게 주는 방식
- 코사인 유사도: 질문과 문단의 조각 분포가 얼마나 같은 방향인지(0~1)
- 규칙(agents/guidance.py)이 못 잡은 질문도 비슷한 문단을 찾아 sLLM 이 되묻거나 답하게 하는 데 쓴다
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

# 뜻은 같은데 글자가 다른 말 — 검색 전에 질문 쪽만 덧붙인다(문서는 그대로)
SYNONYMS = {"분실": "잃어버", "잃어버": "분실", "습득": "주운", "주웠": "습득 주운", "휴대폰": "모형폰 폰", "핸드폰": "휴대폰 모형폰",
            "폰": "휴대폰", "회수": "받는 순서", "수령": "받", "찾으러": "받으러 수령", "본센터": "부산역", "가방": "물건",
            "신분증": "신분 확인", "보관": "보관함", "영업": "운영시간", "몇시": "운영시간"}
# 어디에나 나와 검색을 흐리는 조각(조사·어미)
STOP = {"어요", "해요", "나요", "까요", "세요", "니다", "습니", "는데", "에서", "으로", "하고", "해주", "주세", "알려", "려주",
        "있나", "있어", "인가", "건가", "뭐예", "예요", "이에", "되나", "돼요", "할수", "수있"}


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").lower()
    return re.sub(r"[^0-9a-z가-힣]", "", t)


def grams(text: str) -> Counter:
    t = _norm(text)
    return Counter(g for g in (t[i:i + 2] for i in range(len(t) - 1)) if g not in STOP)


def expand(question: str) -> str:
    extra = [v for k, v in SYNONYMS.items() if k in _norm(question)]
    return question + " " + " ".join(extra)


class Retriever:
    """documents(knowledge.json 목록) → 문단 단위 색인. search(질문) → [{id, topic, title, text, score}]"""

    def __init__(self, documents: list[dict]):
        self.passages = []
        for d in documents:
            for para in d["answer"].split("\n\n"):
                self.passages.append({"topic": d["topic"], "title": d["title"], "text": para})
        bags = [grams(p["title"] + " " + p["text"]) for p in self.passages]
        n = len(bags)
        df = Counter(g for b in bags for g in b)
        self.idf = {g: math.log((n + 1) / (c + 1)) + 1 for g, c in df.items()}
        self.vecs = [self._vec(b) for b in bags]

    def _vec(self, bag: Counter) -> dict:
        v = {g: (1 + math.log(c)) * self.idf.get(g, 0.0) for g, c in bag.items() if g in self.idf}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {g: x / norm for g, x in v.items()}

    def search(self, question: str, k: int = 4) -> list[dict]:
        q = self._vec(grams(expand(question)))
        scored = []
        for i, v in enumerate(self.vecs):
            s = sum(w * v.get(g, 0.0) for g, w in q.items())
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        out, seen = [], set()
        for s, i in scored:
            p = self.passages[i]
            if (p["topic"], p["text"]) in seen:
                continue
            seen.add((p["topic"], p["text"]))
            out.append({"id": i, **p, "score": round(s, 3)})
            if len(out) >= k:
                break
        return out
