"""챗봇 운영 지표 (LLMOps, LF-5 · 11/5 변재원)

한줄 설명: 챗봇이 얼마나 빨리, 어떤 결과로 답하는지를 관제탑이 켜져 있는 동안 세어 두고 `/chat/metrics` 로 보여 준다.
- 질문 원문·답변·토큰·주소는 저장하지 않는다. 숫자(건수·시간)와 결과 이름(status·agent)만 센다
- 관제탑을 다시 켜면 0 부터 다시 센다(메모리). 오래 쌓아 두는 기록이 아니라 지금 상태를 보는 계기판
- 관제 분석 에이전트(agents/ops_analyst.py)가 이 숫자를 읽어 보고서에 넣는다

용어
- p50/p95: 응답 시간을 짧은 순으로 줄 세웠을 때 50%·95% 위치의 값(p95 = "느린 쪽 5% 를 뺀 최대 시간")
- 대체 응답(fallback): 모델이 없거나 검증에 실패해 문서 원문으로 답한 경우
"""
from __future__ import annotations

import threading
import time
from collections import Counter, deque

MAX_SAMPLES = 500          # 응답 시간 표본(최근 것만)


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = min(len(s) - 1, max(0, int(p / 100 * (len(s) - 1) + 0.5)))   # 보통 반올림(round 는 .5 를 짝수로 보냄)
    return round(s[k], 1)


class ChatMetrics:
    """주소별 건수·결과·응답 시간을 센다. 여러 요청이 동시에 와도 안전(lock)."""

    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = threading.Lock()
        self.started_at = clock()
        self._calls: Counter = Counter()         # (kind, outcome) — outcome: ok | rejected | error
        self._status: dict[str, Counter] = {}    # 주소별 응답 status(answered·partial·policy_pending·not_found·items_found …)
        self._agent: Counter = Counter()         # guidance · search · both
        self._generation: Counter = Counter()    # 문서 답변: generated · model_not_configured · …_fallback
        self._ms: dict[str, deque] = {}

    def record(self, kind: str, ms: float, outcome: str = "ok", result: dict | None = None) -> None:
        with self._lock:
            self._calls[(kind, outcome)] += 1
            self._ms.setdefault(kind, deque(maxlen=MAX_SAMPLES)).append(max(0.0, float(ms)))
            if outcome == "ok" and isinstance(result, dict):
                if isinstance(result.get("status"), str):
                    self._status.setdefault(kind, Counter())[result["status"]] += 1
                if kind == "question" and isinstance(result.get("agent"), str):
                    self._agent[result["agent"]] += 1
                if isinstance(result.get("generation_status"), str):
                    self._generation[result["generation_status"]] += 1

    def snapshot(self) -> dict:
        with self._lock:
            kinds = sorted({k for k, _ in self._calls} | set(self._ms))
            per = {}
            for k in kinds:
                ok, rej, err = (self._calls[(k, o)] for o in ("ok", "rejected", "error"))
                ms = list(self._ms.get(k, []))
                per[k] = {"total": ok + rej + err, "ok": ok, "rejected": rej, "error": err,
                          "p50_ms": _pct(ms, 50), "p95_ms": _pct(ms, 95), "max_ms": round(max(ms), 1) if ms else None}
            q_status = self._status.get("question", Counter())     # 비율은 챗봇 질문 응답만으로 계산
            answered = sum(q_status.values())

            def rate(*names):
                return round(100 * sum(q_status[n] for n in names) / answered) if answered else None
            return {
                "since": round(self.started_at), "uptime_s": round(self._clock() - self.started_at),
                "requests": per,
                "status": dict(q_status.most_common()),
                "status_by_kind": {k: dict(c.most_common()) for k, c in sorted(self._status.items())},
                "agent": dict(self._agent.most_common()),
                "generation": dict(self._generation.most_common()),
                "rates_pct": {
                    "answered": rate("answered"),
                    "pending_policy": rate("policy_pending", "partial"),   # 확정 안 된 운영값이 섞인 답
                    "not_understood": rate("not_found", "clarification_needed", "search_needs_details"),
                    "items_found": rate("items_found"),
                },
                "privacy": "질문 원문·답변·토큰은 저장하지 않음(건수·시간·결과 이름만)",
            }


__all__ = ["ChatMetrics"]
