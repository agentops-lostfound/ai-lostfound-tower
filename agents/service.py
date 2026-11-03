"""관제탑 서비스 — LF-14 (docs/design/architecture.md).

한줄 설명: 화면(웹·직원 화면)이 보낸 반환 요청을 검사하고, 반환 흐름을 한 번에 하나씩 실행하고, 기록을 남긴다.

- HTTP(FastAPI)는 agents/api.py 가 이 서비스를 감싸기만 한다. 규칙은 모두 여기 있다(FastAPI 없이 시험 가능).
- 지키는 것
  - 같은 사례 번호로 두 번 실행하지 않는다(로봇이 두 번 움직이는 사고 방지) → "duplicate"
  - 로봇은 하나 → 반환 흐름은 동시에 하나만. 실행 중에 온 요청은 기다리지 않고 "busy"
  - 요청에는 개인정보를 받지 않는다: 사례 번호·접수 번호(영문·숫자·-·_ 32자 이하)와 관문 결과(참/거짓)만
"""
from __future__ import annotations

import re
import threading
from dataclasses import fields
from typing import Callable

from agents.contracts import DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED, DECISIONS
from agents.records import MemoryRecorder, Recorder
from agents.supervisor import Outcome, ReturnRequest, run_return

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
GATE_FIELDS = [f.name for f in fields(ReturnRequest) if f.name not in ("case_id", "item_id")]
ALLOWED = {"case_id", "item_id", *GATE_FIELDS}


class RequestError(ValueError):
    """요청 형식 오류(HTTP 422)."""


class Unavailable(RuntimeError):
    """기록 저장소(DB)에 닿지 않아 안전하게 실행할 수 없음(HTTP 503). 중복 확인을 못 하면 로봇을 움직이지 않는다."""


class Conflict(RuntimeError):
    """중복 사례 번호 또는 다른 반환 진행 중(HTTP 409). kind: duplicate | busy"""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def parse_request(payload: object) -> ReturnRequest:
    """화면이 보낸 JSON → ReturnRequest. 모르는 칸·잘못된 값은 RequestError."""
    if not isinstance(payload, dict):
        raise RequestError("JSON 객체여야 합니다")
    unknown = sorted(set(payload) - ALLOWED)
    if unknown:
        raise RequestError(f"모르는 칸: {unknown} (개인정보는 보내지 않습니다)")
    for key in ("case_id", "item_id"):
        v = payload.get(key)
        if not isinstance(v, str) or not ID_RE.match(v):
            raise RequestError(f"{key}: 영문·숫자·-·_ 1~32자")
    gates = {}
    for key in GATE_FIELDS:
        if key not in payload:
            raise RequestError(f"{key}: 빠짐(관문 결과는 모두 보내야 합니다)")
        if not isinstance(payload[key], bool):
            raise RequestError(f"{key}: true/false 만")
        gates[key] = payload[key]
    return ReturnRequest(case_id=payload["case_id"], item_id=payload["item_id"], **gates)


class TowerService:
    def __init__(self, backend_factory: Callable[[], object], reporter, recorder: Recorder | None = None,
                 reviewer=None, flow: Callable = run_return):
        self.backend_factory = backend_factory   # 요청마다 부품 묶음을 얻는 함수(진짜 부품이면 같은 객체를 돌려줘도 됨)
        self.reporter = reporter
        self.recorder = recorder if recorder is not None else MemoryRecorder()
        self.reviewer = reviewer
        self.flow = flow
        self._run_lock = threading.Lock()

    def start_return(self, payload: object) -> dict:
        req = parse_request(payload)
        if not self._run_lock.acquire(blocking=False):
            raise Conflict("busy", "다른 반환이 진행 중입니다(로봇 1대). 끝난 뒤 다시 요청하세요")
        try:
            try:
                seen = self.recorder.has(req.case_id)
            except Exception as e:
                raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__}) — 중복 확인을 못 해 실행하지 않음") from e
            if seen:
                raise Conflict("duplicate", f"이미 처리한 사례 번호: {req.case_id}")
            be = self.backend_factory()
            try:
                out = self.flow(req, be, self.reporter, reviewer=self.reviewer).to_dict()
            except Exception as e:   # 부품이 약속을 어기고 예외를 던진 경우 → 정지 시도 + 직원 확인
                out = self._crash(req, be, e)
            if out.get("decision") not in DECISIONS:
                raise RuntimeError(f"알 수 없는 결정: {out.get('decision')}")
            try:
                self.recorder.save(req.item_id, out)
                out["recorded"] = True
            except Exception as e:   # 반환은 이미 끝남 → 결과는 돌려주고, 기록 실패만 알림
                out["recorded"] = False
                try:
                    self.reporter.alert(req.case_id, f"반환 기록 저장 실패({type(e).__name__}) — 직원이 기록 확인",
                                        f"물건 {req.item_id}")
                except Exception:
                    pass
            self._team_summary(req, out)
            return out
        finally:
            self._run_lock.release()

    def _team_summary(self, req: ReturnRequest, out: dict) -> None:
        """팀 대화 채널에 반환 1건당 결과 한 줄(물건·사례 번호만). 실패해도 반환 결과에는 영향 없음."""
        icon = {DECISION_RETURNED: "✅ 반환 완료", DECISION_REJECTED: "⛔ 반환 안 함",
                DECISION_STAFF: "🙋 직원 확인 필요", DECISION_STOPPED: "🛑 로봇 정지"}.get(out.get("decision"), "❔")
        saved = "" if out.get("recorded", True) else " · 기록 저장 실패"
        try:
            self.reporter.team(f"[{req.case_id}] 물건 {req.item_id} · {icon}",
                               f"{out.get('reason', '')} · {out.get('seconds', 0):.1f}초{saved}")
        except Exception:
            pass

    def _crash(self, req: ReturnRequest, be, err: Exception) -> dict:
        try:
            stopped = bool((be.robot_stop() or {}).get("ok"))
        except Exception:
            stopped = False
        reason = f"흐름 오류({type(err).__name__}) — 로봇 정지{'' if stopped else ' 실패'}, 직원 확인"
        try:
            self.reporter.alert(req.case_id, reason, f"물건 {req.item_id}")
        except Exception:
            pass
        return Outcome(req.case_id, DECISION_STOPPED, reason).to_dict()

    def get_case(self, case_id: str) -> dict | None:
        if not ID_RE.match(case_id or ""):
            raise RequestError("case_id: 영문·숫자·-·_ 1~32자")
        try:
            return self.recorder.get(case_id)
        except Exception as e:
            raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__})") from e

    def recent(self, limit: int = 20) -> list[dict]:
        try:
            return self.recorder.recent(max(1, min(limit, 100)))
        except Exception as e:
            raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__})") from e

    def health(self) -> dict:
        try:   # 상태 확인은 부품이 고장 나도 답해야 한다
            be = self.backend_factory()
            sources = be.sources() if callable(getattr(be, "sources", None)) else {"all": type(be).__name__}
        except Exception as e:
            sources = {"error": type(e).__name__}
        return {"ok": True, "busy": self._run_lock.locked(), "reviewer": self.reviewer is not None,
                "send": not getattr(self.reporter, "dry_run", True), "sources": sources}


def demo_backend_factory() -> Callable[[], object]:
    """진짜 부품이 없을 때 쓰는 시연용 부품: 보관함에 W01~W07, 접수 번호 A-W01 ~ A-W07.

    요청마다 새 가짜 부품을 만든다(집기 시도 횟수 같은 상태가 다음 요청에 남지 않게).
    """
    import json
    from pathlib import Path

    from agents.backends import CompositeBackend
    from agents.tools import MockBackend

    spec = json.loads((Path(__file__).resolve().parent.parent / "evaluation" / "test_cases.json").read_text(encoding="utf-8"))
    objs = spec["objects"]

    def make():
        bin_items = [{"object_id": oid, "features": objs[oid], "center": [100 + 80 * i, 240]}
                     for i, oid in enumerate(spec["bin"])]
        db = {f"A-{oid}": {"status": "본센터 보관", "features": objs[oid], "object_id": oid} for oid in objs}
        return CompositeBackend(fallback=MockBackend(bin_items=bin_items, db=db))
    return make


__all__ = ["TowerService", "RequestError", "Conflict", "Unavailable", "parse_request", "demo_backend_factory", "GATE_FIELDS"]
