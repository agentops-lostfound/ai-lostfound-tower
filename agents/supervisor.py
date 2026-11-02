"""메인 AI(Supervisor) 반환 흐름 — LF-14.

한줄 설명: 분실인 확인부터 로봇 반환까지 순서대로 진행하되, 안전 규칙은 AI 판단이 아니라 코드로 강제한다.

흐름
    [웹] 동의 → 본인인증(OCR) → 확인 질문 → 메인 AI 승인·수령 예약
    [본센터] 직원 실물 신분증 대조 → 안쪽 특징 확인 → 직원 최종 확인
    [로봇] 탑뷰 촬영 → 매칭 → 사전 접근 → 집기(실패 시 1번 재시도) → 집기 확인 → 바구니 전달

안전 규칙(바꿀 수 없음)
    - 동의·인증·확인 질문을 통과하지 못하면 승인하지 않는다
    - 신분증·안쪽 특징이 다르거나 직원 확인이 없으면 로봇을 움직이지 않는다
    - 매칭이 불확실하거나 없으면 자동 반환하지 않는다(직원 확인)
    - 로봇이 실패하면 정지하고 알린다
LLM 검토(reviewer)를 붙일 수 있지만, 결과를 '더 안전한 쪽(직원 확인)'으로만 바꿀 수 있다.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from agents.contracts import (
    DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED, MATCH_OK, validate_detection,
)

MAX_GRASP_ATTEMPTS = 2   # 첫 시도 + 재시도 1번 (추정, LF-19 시험 후 확정)


@dataclass
class ReturnRequest:
    case_id: str
    item_id: str
    consent: bool = True
    id_verified: bool = True          # 웹 신분증 OCR 인증
    quiz_passed: bool = True          # 확인 질문
    visitor_id_match: bool = True     # 방문 때 실물 신분증 대조
    inner_feature_ok: bool = True     # 직원이 안쪽 특징 확인
    staff_confirmed: bool = True      # 직원 최종 확인 버튼


@dataclass
class Outcome:
    case_id: str
    decision: str
    reason: str
    approved: bool = False            # 메인 AI 승인(수령 예약) 여부
    matched_index: int | None = None
    matched_object: str | None = None   # 탑뷰 검출에 붙은 물건 ID(있을 때)
    steps: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


Reviewer = Callable[[dict], tuple[str, str]]   # 입력 요약 → ("ok" | "hold", 메모)


@dataclass
class Ctx:
    """단계 사이에 넘기는 작업 상태(LangGraph 상태로도 그대로 쓴다)."""
    req: ReturnRequest
    backend: object
    reporter: object
    reviewer: Reviewer | None = None
    out: Outcome | None = None
    t0: float = 0.0
    item: dict | None = None
    detections: list = field(default_factory=list)
    match: dict | None = None

    def step(self, name: str, detail: str = "") -> None:
        self.out.steps.append(name)
        self.reporter.progress(self.req.case_id, name, detail)

    def finish(self, decision: str, reason: str, alert: bool = False) -> bool:
        self.out.decision, self.out.reason = decision, reason
        if alert:
            self.reporter.alert(self.req.case_id, reason, f"물건 {self.req.item_id}")
        self.out.seconds = round(time.perf_counter() - self.t0, 4)
        return True   # True = 여기서 끝


# 각 단계는 끝났으면 True, 다음 단계로 가면 False 를 돌려준다
def web_gate(c: Ctx) -> bool:
    """1. 웹 단계: 코드로 강제하는 관문 → 메인 AI 승인"""
    req, be = c.req, c.backend
    if not req.consent:
        return c.finish(DECISION_REJECTED, "동의 거부 — 안내 후 종료")
    if not req.id_verified:
        return c.finish(DECISION_REJECTED, "본인인증 실패")
    if not req.quiz_passed:
        return c.finish(DECISION_REJECTED, "확인 질문 미통과 — 승인하지 않음", alert=True)
    c.item = be.db_get_item(req.item_id)
    if c.item is None:
        return c.finish(DECISION_STAFF, "물건 기록 없음", alert=True)
    if c.reviewer is not None:
        verdict, note = c.reviewer({"case": req.case_id, "item_id": req.item_id, "status": c.item.get("status")})
        if verdict != "ok":
            return c.finish(DECISION_STAFF, f"메인 AI 검토 보류: {note}", alert=True)
    c.out.approved = True
    be.db_set_status(req.item_id, "승인·수령 예약")
    c.step("메인 AI 승인 · 수령 예약")
    return False


def visit_gate(c: Ctx) -> bool:
    """2. 본센터 방문: 사람 확인"""
    req, be = c.req, c.backend
    if not req.visitor_id_match:
        be.db_set_status(req.item_id, "반환 보류")
        return c.finish(DECISION_REJECTED, "방문자 신분증 불일치 — 반환하지 않음", alert=True)
    if not req.inner_feature_ok:
        be.db_set_status(req.item_id, "반환 보류")
        return c.finish(DECISION_REJECTED, "안쪽 특징 불일치 — 반환하지 않음", alert=True)
    if not req.staff_confirmed:
        return c.finish(DECISION_STAFF, "직원 최종 확인 대기")
    c.step("직원 확인 완료")
    return False


def locate(c: Ctx) -> bool:
    """3. 탑뷰 촬영 → 매칭(불확실하면 자동 반환 안 함)"""
    dets = c.backend.vision_topview()
    c.detections = [d for d in dets if not validate_detection(d)]
    c.step("탑뷰 촬영", f"물건 {len(c.detections)}개 검출")
    if not c.detections:
        return c.finish(DECISION_STAFF, "보관함에서 물건을 찾지 못함", alert=True)
    m = c.backend.match_item(c.item["features"], c.detections)
    if m["status"] != MATCH_OK:
        return c.finish(DECISION_STAFF, f"매칭 불확실({m['status']}) — 자동 반환 안 함", alert=True)
    c.match = m
    c.out.matched_index = m["index"]
    c.out.matched_object = c.detections[m["index"]].get("object_id")
    c.step("매칭 완료", f"점수 {m['score']} · 차이 {m['margin']}")
    return False


def approach(c: Ctx) -> bool:
    """4. 사전 접근(일반 위치 제어)"""
    c.backend.db_set_status(c.req.item_id, "반환 중")
    r = c.backend.robot_approach(c.detections[c.match["index"]]["center"])
    if not r["ok"]:
        c.backend.robot_stop()
        return c.finish(DECISION_STOPPED, f"사전 접근 실패: {r['reason']}", alert=True)
    c.step("사전 접근 완료")
    return False


def grasp(c: Ctx) -> bool:
    """5. 근거리 집기(SmolVLA) — 실패하면 1번만 다시"""
    for attempt in range(1, MAX_GRASP_ATTEMPTS + 1):
        g = c.backend.robot_grasp()
        v = c.backend.robot_verify_grasp() if g["ok"] else g
        if g["ok"] and v["ok"]:
            c.step("집기 성공", f"{attempt}번째 시도")
            return False
        c.reporter.progress(c.req.case_id, "집기 실패", f"{attempt}번째 시도: {v['reason']}")
    c.backend.robot_stop()
    return c.finish(DECISION_STOPPED, "집기 실패 — 정지, 직원 호출", alert=True)


def deliver(c: Ctx) -> bool:
    """6. 바구니 전달(일반 위치 제어)"""
    d = c.backend.robot_deliver()
    if not d["ok"]:
        c.backend.robot_stop()
        return c.finish(DECISION_STOPPED, f"바구니 전달 실패: {d['reason']}", alert=True)
    c.backend.db_set_status(c.req.item_id, "인계 완료")
    c.step("바구니 전달 완료")
    return c.finish(DECISION_RETURNED, "반환 완료")


STAGES = [("web_gate", web_gate), ("visit_gate", visit_gate), ("locate", locate),
          ("approach", approach), ("grasp", grasp), ("deliver", deliver)]


def new_ctx(req: ReturnRequest, backend, reporter, reviewer: Reviewer | None = None) -> Ctx:
    return Ctx(req, backend, reporter, reviewer, Outcome(req.case_id, DECISION_STAFF, ""), time.perf_counter())


def run_return(req: ReturnRequest, backend, reporter, reviewer: Reviewer | None = None) -> Outcome:
    """단계를 순서대로 실행(LangGraph 없이). 그래프판은 agents/graph.py — 같은 단계 함수를 쓴다."""
    c = new_ctx(req, backend, reporter, reviewer)
    for _, stage in STAGES:
        if stage(c):
            break
    return c.out
