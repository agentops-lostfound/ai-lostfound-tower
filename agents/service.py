"""관제탑 서비스 — LF-14 (docs/design/architecture.md).

한줄 설명: 화면(웹·직원 화면)이 보낸 반환 요청을 검사하고, 반환 흐름을 한 번에 하나씩 실행하고, 기록을 남긴다.

- HTTP(FastAPI)는 agents/api.py 가 이 서비스를 감싸기만 한다. 규칙은 모두 여기 있다(FastAPI 없이 시험 가능).
- 지키는 것
  - 같은 사례 번호로 두 번 실행하지 않는다(로봇이 두 번 움직이는 사고 방지) → "duplicate"
  - 로봇은 하나 → 반환 흐름은 동시에 하나만. 실행 중에 온 요청은 기다리지 않고 "busy"
  - 요청에는 개인정보를 받지 않는다: 사례 번호·접수 번호(영문·숫자·-·_ 32자 이하)와 관문 결과(참/거짓)만
- 2단계 연결(11/3): 웹은 create_claim(찾기 요청 + 웹 관문 3개 + 예약) → 방문 때 직원 화면은 start_return 에
  claim_id + 현장 관문 3개만 보낸다. 웹 관문은 저장된 값만 쓴다(직원이 다시 입력하지 않음)
"""
from __future__ import annotations

import re
import threading
from dataclasses import fields
from typing import Callable

from agents.claims import ClaimError, ClaimStore, MemoryClaimStore, parse_claim, public_view, web_gates
from agents.intake import IntakeError, IntakeStore, MemoryIntakeStore, parse_features, parse_intake, receipt, valid_item_id
from agents.contracts import (CLAIM_ID_RE, DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED,
                              DECISIONS, HANDOVER_DONE, HANDOVER_HOLD, HANDOVER_WAIT, HOLD_REASONS)
from agents.records import MemoryRecorder, Recorder
from agents.supervisor import Outcome, ReturnRequest, run_return

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
GATE_FIELDS = [f.name for f in fields(ReturnRequest) if f.name not in ("case_id", "item_id")]
ALLOWED = {"case_id", "item_id", *GATE_FIELDS}
VISIT_GATES = ["visitor_id_match", "inner_feature_ok", "staff_confirmed"]   # 본센터 방문 때 직원 화면이 채움
VISIT_ALLOWED = {"claim_id", "case_id", *VISIT_GATES}


class RequestError(ValueError):
    """요청 형식 오류(HTTP 422)."""


class Unavailable(RuntimeError):
    """기록 저장소(DB)에 닿지 않아 안전하게 실행할 수 없음(HTTP 503). 중복 확인을 못 하면 로봇을 움직이지 않는다."""


class NotFound(LookupError):
    """없는 찾기 번호(HTTP 404)."""


class Conflict(RuntimeError):
    """중복 사례 번호 또는 다른 반환 진행 중(HTTP 409). kind: duplicate | busy | state(인계할 수 없는 상태)"""

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


def parse_visit(payload: dict) -> tuple[str, str | None, dict]:
    """직원 화면(2단계)의 요청 → (claim_id, case_id 또는 None, 현장 관문 3개)."""
    unknown = sorted(set(payload) - VISIT_ALLOWED)
    if unknown:
        raise RequestError(f"모르는 칸: {unknown} (방문 확인은 claim_id·case_id·현장 관문 3개만)")
    cid = payload.get("claim_id")
    if not isinstance(cid, str) or not CLAIM_ID_RE.match(cid):
        raise RequestError("claim_id: 찾기 번호 형식(예: C-20261103-0001)")
    case = payload.get("case_id")
    if case is not None and (not isinstance(case, str) or not ID_RE.match(case)):
        raise RequestError("case_id: 영문·숫자·-·_ 1~32자")
    gates = {}
    for key in VISIT_GATES:
        if not isinstance(payload.get(key), bool):
            raise RequestError(f"{key}: true/false 필요(직원 화면에서 확인)")
        gates[key] = payload[key]
    return cid, case, gates


class TowerService:
    def __init__(self, backend_factory: Callable[[], object], reporter, recorder: Recorder | None = None,
                 reviewer=None, flow: Callable = run_return, claims: ClaimStore | None = None,
                 intake: IntakeStore | None = None):
        self.backend_factory = backend_factory   # 요청마다 부품 묶음을 얻는 함수(진짜 부품이면 같은 객체를 돌려줘도 됨)
        self.reporter = reporter
        self.recorder = recorder if recorder is not None else MemoryRecorder()
        self.reviewer = reviewer
        self.flow = flow
        self.claims = claims if claims is not None else MemoryClaimStore()
        self.intake = intake if intake is not None else MemoryIntakeStore()
        self._run_lock = threading.Lock()

    # ---------- 습득물 접수(등록기계 화면) ----------
    def list_places(self, machine_id: str, limit: int = 10) -> list[dict]:
        from agents.contracts import MACHINE_LETTERS
        if machine_id not in MACHINE_LETTERS:
            raise RequestError(f"machine_id: {list(MACHINE_LETTERS)} 중 하나")
        try:
            return self.intake.places(machine_id, max(1, min(int(limit), 30)))
        except IntakeError as e:
            raise RequestError(str(e)) from e
        except Exception as e:
            raise Unavailable(f"접수 저장소 연결 실패({type(e).__name__})") from e

    def create_item(self, payload: object) -> dict:
        """등록기계: 접수 → 접수 번호. 연락처는 저장만 하고 돌려주지 않는다."""
        try:
            intake = parse_intake(payload)
            row = self.intake.create(intake)
        except IntakeError as e:
            raise RequestError(str(e)) from e
        except Exception as e:
            raise Unavailable(f"접수 저장소 연결 실패({type(e).__name__})") from e
        return receipt(row)

    def set_item_features(self, item_id: str, payload: object) -> dict:
        """뒤에서 도는 Qwen 작업: 특징 채우기. 돌려주는 값은 공개 특징만(비공개 특징 = 확인 질문 정답)."""
        from agents.contracts import public_card
        if not valid_item_id(item_id):
            raise RequestError("item_id: 접수 번호 형식(예: A-20261103-0001)")
        try:
            feats = parse_features(payload)
            ok = self.intake.set_features(item_id, feats)
        except IntakeError as e:
            raise RequestError(str(e)) from e
        except Exception as e:
            raise Unavailable(f"접수 저장소 연결 실패({type(e).__name__})") from e
        if not ok:
            raise NotFound(f"없는 접수 번호: {item_id}")
        return {"item_id": item_id, "category": feats.get("category"), "features": public_card(
            {k: v for k, v in feats.items() if k != "category"})}

    # ---------- 찾기 요청(웹) ----------
    def create_claim(self, payload: object) -> dict:
        try:
            claim = parse_claim(payload)
        except ClaimError as e:
            raise RequestError(str(e)) from e
        try:
            row = self.claims.create(claim)
        except ClaimError as e:          # 없는 물건 등
            raise RequestError(str(e)) from e
        except Exception as e:
            raise Unavailable(f"찾기 요청 저장소 연결 실패({type(e).__name__})") from e
        return public_view(row)

    def get_claim(self, claim_id: str) -> dict | None:
        if not CLAIM_ID_RE.match(claim_id or ""):
            raise RequestError("claim_id: 찾기 번호 형식(예: C-20261103-0001)")
        try:
            row = self.claims.get(claim_id)
        except Exception as e:
            raise Unavailable(f"찾기 요청 저장소 연결 실패({type(e).__name__})") from e
        return public_view(row) if row else None

    def _request_from_claim(self, payload: dict) -> tuple[ReturnRequest, str]:
        cid, case, visit = parse_visit(payload)
        try:
            row = self.claims.get(cid)
        except Exception as e:
            raise Unavailable(f"찾기 요청 저장소 연결 실패({type(e).__name__}) — 웹 확인 결과를 못 읽어 실행하지 않음") from e
        if row is None:
            raise NotFound(f"없는 찾기 번호: {cid}")
        if row.get("status") != "booked":
            raise Conflict("duplicate", f"이미 방문 처리됐거나 취소된 찾기 요청: {cid} ({row.get('status')})")
        return ReturnRequest(case_id=case or f"R-{cid}", item_id=row["item_id"], **web_gates(row), **visit), cid

    def start_return(self, payload: object) -> dict:
        """1단계(관문 6개를 한 번에) 또는 2단계(claim_id + 현장 관문 3개) 요청을 받는다."""
        claim_id = None
        if isinstance(payload, dict) and "claim_id" in payload:
            req, claim_id = self._request_from_claim(payload)
        else:
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
            if claim_id:
                out["claim_id"] = claim_id
                if out["decision"] == DECISION_RETURNED:
                    try:
                        self.claims.mark_visited(claim_id)
                    except Exception as e:   # 예약이 그대로면 같은 찾기 요청으로 다시 반환될 수 있음 → 직원에게 알림
                        try:
                            self.reporter.alert(req.case_id, f"방문 처리 저장 실패({type(e).__name__}) — 찾기 {claim_id} 다시 반환 금지, 직원 확인",
                                                f"물건 {req.item_id}")
                        except Exception:
                            pass
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

    def _waiting_item(self, case_id: str):
        """인계할 물건 찾기: 반환 기록(바구니까지 전달) → 물건 → 지금 상태. (부품, 물건 번호, 상태)"""
        if not ID_RE.match(case_id or ""):
            raise RequestError("case_id: 영문·숫자·-·_ 1~32자")
        try:
            row = self.recorder.get(case_id)
        except Exception as e:
            raise Unavailable(f"기록 저장소 연결 실패({type(e).__name__})") from e
        if row is None:
            raise NotFound(f"반환 기록 없음: {case_id}")
        if row.get("decision") != DECISION_RETURNED:
            raise Conflict("state", f"바구니까지 전달된 반환이 아님(결과 {row.get('decision')}) — 인계할 물건 없음")
        item_id = row.get("item_id")
        be = self.backend_factory()
        item = be.db_get_item(item_id)
        if item is None:
            raise NotFound(f"물건 기록 없음: {item_id}")
        return be, item_id, item.get("status")

    def handover(self, case_id: str, payload: object) -> dict:
        """직원 화면: 바구니의 물건을 분실인에게 건넸다 → 물건 상태 인계 대기 → 인계 완료 (11/4).
        본문은 {"staff_confirmed": true} 만 받는다. 로봇은 움직이지 않으므로 반환 실행 잠금을 쓰지 않는다."""
        if not isinstance(payload, dict) or set(payload) != {"staff_confirmed"} or payload["staff_confirmed"] is not True:
            raise RequestError('본문은 {"staff_confirmed": true} 만 보냅니다(직원이 건넨 것을 확인한 뒤)')
        be, item_id, status = self._waiting_item(case_id)
        if status == HANDOVER_DONE:
            raise Conflict("duplicate", f"이미 인계 완료: 물건 {item_id}")
        if status != HANDOVER_WAIT:
            raise Conflict("state", f"인계 대기 상태가 아님(지금 {status}) — 직원이 물건 위치 확인")
        r = be.db_set_status(item_id, HANDOVER_DONE, changed_by="staff")
        if not (r or {}).get("ok"):
            raise Unavailable(f"상태 기록 실패: {(r or {}).get('reason', '')}")
        try:
            self.reporter.progress(case_id, "인계 완료", f"물건 {item_id} · 직원이 분실인에게 건넴")
        except Exception:
            pass
        return {"case_id": case_id, "item_id": item_id, "status": HANDOVER_DONE}

    def hold_handover(self, case_id: str, payload: object) -> dict:
        """직원 화면: 인계 대기 중에 건네지 않기로 함(본인 아님 등) → 반환 보류 + 경보 (11/4).
        본문 {"reason": HOLD_REASONS 중 하나}. 자유 입력은 받지 않는다(기록·알림에 개인정보가 섞이지 않게)."""
        if not isinstance(payload, dict) or set(payload) != {"reason"} or payload["reason"] not in HOLD_REASONS:
            raise RequestError(f'본문은 {{"reason": {" | ".join(HOLD_REASONS)}}} 만 보냅니다')
        be, item_id, status = self._waiting_item(case_id)
        if status == HANDOVER_HOLD:
            raise Conflict("duplicate", f"이미 반환 보류: 물건 {item_id}")
        if status != HANDOVER_WAIT:
            raise Conflict("state", f"인계 대기 상태가 아님(지금 {status}) — 인계 취소할 수 없음")
        r = be.db_set_status(item_id, HANDOVER_HOLD, changed_by="staff")
        if not (r or {}).get("ok"):
            raise Unavailable(f"상태 기록 실패: {(r or {}).get('reason', '')}")
        try:
            self.reporter.alert(case_id, f"인계 취소 → 반환 보류({payload['reason']})", f"물건 {item_id} · 바구니에서 꺼내 보관, 직원 확인")
        except Exception:
            pass
        return {"case_id": case_id, "item_id": item_id, "status": HANDOVER_HOLD, "reason": payload["reason"]}

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

    요청마다 새 가짜 부품을 만든다(집기 시도 횟수 같은 상태가 다음 요청에 남지 않게). 물건 상태만 이어진다.
    """
    import json
    from pathlib import Path

    from agents.backends import CompositeBackend
    from agents.tools import MockBackend

    spec = json.loads((Path(__file__).resolve().parent.parent / "evaluation" / "test_cases.json").read_text(encoding="utf-8"))
    objs = spec["objects"]
    # 물건 상태는 관제탑이 켜져 있는 동안 요청끼리 이어진다(반환 → 인계 대기 → 직원 인계 완료를 시연할 수 있게, 11/4)
    db = {f"A-{oid}": {"status": "본센터 보관", "features": objs[oid], "object_id": oid} for oid in objs}

    def make():
        bin_items = [{"object_id": oid, "features": objs[oid], "center": [100 + 80 * i, 240]}
                     for i, oid in enumerate(spec["bin"])]
        return CompositeBackend(fallback=MockBackend(bin_items=bin_items, db=db))
    return make


__all__ = ["TowerService", "RequestError", "Conflict", "Unavailable", "NotFound", "parse_request", "demo_backend_factory", "GATE_FIELDS"]
