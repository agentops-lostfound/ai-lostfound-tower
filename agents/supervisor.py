"""메인 AI(Supervisor) 반환 흐름 — LF-14.

한줄 설명: 분실인 확인부터 로봇 반환까지 순서대로 진행하되, 안전 규칙은 AI 판단이 아니라 코드로 강제한다.

흐름
    [웹] 동의 → 본인인증(OCR) → 확인 질문 → 메인 AI 승인·수령 예약
    [본센터] 직원 실물 신분증 대조 → 안쪽 특징 확인 → 직원 최종 확인
    [로봇] 탑뷰 촬영 → 매칭 → 사전 접근 → 집기(실패 시 1번 재시도) → 집기 확인 → 바구니 전달(인계 대기)
    [직원 보관 선반] 11/9: 칸이 꽉 차 선반에 둔 물건은 로봇 단계를 모두 건너뛰고 인계 대기 → 직원이 직접 가져와 교차 검증 후 건넴
    [직원] 분실인에게 건넴 확인 → 인계 완료 (service.handover, 이 흐름 밖)

안전 규칙(바꿀 수 없음)
    - 동의·인증·확인 질문을 통과하지 못하면 승인하지 않는다
    - 신분증·안쪽 특징이 다르거나 직원 확인이 없으면 로봇을 움직이지 않는다
    - 매칭이 불확실하거나 없으면 자동 반환하지 않는다(직원 확인)
    - 작업대 mm 좌표(카메라 보정 결과)가 없으면 로봇을 움직이지 않는다(직원 확인)
    - GPU 사용권(STT·Qwen 해제 확인)을 받지 못하면 로봇을 움직이지 않는다(직원 확인)
    - 로봇이 실패하면 정지하고 알린다
LLM 검토(reviewer)를 붙일 수 있지만, 결과를 '더 안전한 쪽(직원 확인)'으로만 바꿀 수 있다.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable

from agents.contracts import (
    DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, DECISION_STOPPED, HANDOVER_WAIT, MATCH_OK, NONE,
    STAFF_STOP_REASON, UNKNOWN, valid_point_mm, validate_detection,
)
from agents.tools import feature_similarity

MAX_GRASP_ATTEMPTS = 2   # 첫 시도 + 재시도 1번 (추정, LF-19 시험 후 확정)
# 닮은 물건 검사(11/3, docs/design/swap_guide.md 7장): 고른 물건이 다른 보관 중 물건과도 이만큼 닮았으면 자동 반환 안 함
LOOKALIKE_MIN = 0.6      # 이 점수 이상 닮아야 "닮은 물건" 후보(매칭 기준과 같음)
LOOKALIKE_MARGIN = 0.15  # 찾는 물건 점수와 차이가 이보다 작으면 구별할 수 없다고 본다(매칭 차이 기준과 같음)


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
    staff_shelf: bool = False         # 11/9 물건이 직원 보관 선반(S-n)에 있음 — 화면이 보내지 못하고 서버가 보관함 정답지로 정함


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
    consult: Callable | None = None   # 11/8 관제탑 메인 AI(agents/tower_brain.py): 매칭이 애매할 때 근거를 더 모음. None 이면 예전 그대로
    brain_note: str = ""              # 메인 AI 추천(직원 알림에 붙임)
    talk: object | None = None        # 11/9 에이전트 대화(agents/agent_talk.py). None 이면 예전 그대로
    slot_area: Callable | None = None # 11/9 item_id → {"slot_id", "bounds_mm"} (로봇팔 에이전트가 DB 에이전트에게 묻는 칸 범위)
    last_status: str = ""             # 이 흐름이 마지막으로 바꾼 물건 상태
    grasp_started: bool = False       # 로봇이 물건을 집으려고 했는지(했으면 물건 위치를 직원이 확인해야 함)

    def step(self, name: str, detail: str = "") -> None:
        self.out.steps.append(name)
        self.reporter.progress(self.req.case_id, name, detail)

    def finish(self, decision: str, reason: str, alert: bool = False) -> bool:
        self.out.decision, self.out.reason = decision, reason
        # 11/8 무작위 시험: 직원 확인·정지로 끝났는데 물건 상태가 '승인·수령 예약'·'반환 중'에 남아(되돌릴 API 없음) 다음 처리가 꼬였다.
        # 로봇이 물건을 건드리기 전에 끝났으면 물건은 보관함 그대로 → '본센터 보관'으로 되돌린다(집기를 시도했으면 직원 확인 위해 그대로)
        if (decision in (DECISION_STAFF, DECISION_STOPPED) and self.last_status in ("승인·수령 예약", "반환 중")
                and not self.grasp_started and "직원 최종 확인 대기" not in reason):
            try:
                self.backend.db_set_status(self.req.item_id, "본센터 보관")
            except Exception:
                pass
        if alert:
            self.reporter.alert(self.req.case_id, reason, f"물건 {self.req.item_id}")
        self.out.seconds = round(time.perf_counter() - self.t0, 4)
        return True   # True = 여기서 끝


def _stop(c: Ctx) -> str:
    """로봇 정지. 정지 자체가 실패하면 알림 문구에 붙일 말을 돌려준다(약속: 정지 실패 → 직원 호출)."""
    r = c.backend.robot_stop()
    if isinstance(r, dict) and r.get("ok"):
        return " · 로봇 정지(직원이 확인 후 원점 복귀 버튼)"
    return " · 정지 실패 — 직원 즉시 호출"


def _set_status(c: Ctx, status: str) -> bool:
    """상태 변경. 실패하면 False(약속: 상태 변경 실패 → 로봇을 움직이지 않음)."""
    r = c.backend.db_set_status(c.req.item_id, status)
    ok = isinstance(r, dict) and bool(r.get("ok"))
    if ok:
        c.last_status = status
    return ok


def safe_note(note) -> str:
    """검토 모델 메모를 직원 알림에 넣기 전에 거른다(11/8 에이전트 무작위 시험: "@everyone 010-…" 메모가 알림 본문에 그대로 들어감).
    개인정보·멘션·주소가 있으면 정해진 문장, 아니면 60자까지"""
    import re
    from agents.claims import has_pii
    text = " ".join(str(note or "").split())
    if not text or has_pii(text) or re.search(r"@|https?://|<|>|`", text):
        return "모델 메모 생략(형식)"
    return text[:60]


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
            return c.finish(DECISION_STAFF, f"메인 AI 검토 보류: {safe_note(note)}", alert=True)
    if not _set_status(c, "승인·수령 예약"):
        return c.finish(DECISION_STAFF, "상태 기록 실패 — 승인 보류", alert=True)
    c.out.approved = True
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


SHELF_STEP = "직원 보관 선반 · 로봇 없이 직원 인계"


def shelf_handover(c: Ctx) -> bool:
    """2-1. (11/9) 직원 보관 선반 물건: 로봇이 집을 수 없는 곳(보관판 밖)이라 탑뷰·매칭·로봇 단계를 건너뛴다.
    앞의 관문(웹 확인·방문 신분증·안쪽 특징·직원 확인)은 그대로 통과한 뒤에만 오고, 건네기 전 직원 교차 검증도 그대로(인계 대기)"""
    if not c.req.staff_shelf:
        return False
    if not _set_status(c, HANDOVER_WAIT):
        return c.finish(DECISION_STAFF, "상태 기록 실패 — 직원 보관 선반 물건, 직원 확인", alert=True)
    c.step(SHELF_STEP, "직원이 선반에서 가져와 교차 검증 후 건넴")
    return c.finish(DECISION_RETURNED, "직원 보관 선반 물건 — 로봇 안 씀 · 직원 인계 대기(교차 검증)")


def locate(c: Ctx) -> bool:
    """3. 탑뷰 촬영 → 매칭(불확실하면 자동 반환 안 함)"""
    dets = c.backend.vision_topview()
    c.detections = [d for d in dets if not validate_detection(d)]
    c.step("탑뷰 촬영", f"물건 {len(c.detections)}개 검출")
    if not c.detections:
        return c.finish(DECISION_STAFF, "보관함에서 물건을 찾지 못함", alert=True)
    m = c.backend.match_item(c.item["features"], c.detections)
    twin = lookalike(c, c.detections[m["index"]]["features"]) if m["status"] == MATCH_OK else ""
    if (m["status"] != MATCH_OK or twin) and c.consult is not None:
        # 11/8: 바로 직원을 부르기 전에 메인 AI 가 에이전트들과 근거를 더 모음. 진행 여부는 같은 기준(확실 + 닮은 물건 없음)을 코드가 다시 확인
        try:
            got = c.consult(c, m, twin)
        except Exception as e:
            got, c.brain_note = None, f"메인 AI 오류({type(e).__name__})"
        if got is not None:
            dets, m2 = got
            if (isinstance(m2, dict) and m2.get("status") == MATCH_OK and isinstance(m2.get("index"), int)
                    and 0 <= m2["index"] < len(dets) and not lookalike(c, dets[m2["index"]]["features"])):
                c.detections, m, twin = dets, m2, ""
                c.step("메인 AI 재확인", c.brain_note)
    note = f" · {c.brain_note}" if c.brain_note else ""
    if m["status"] != MATCH_OK:
        return c.finish(DECISION_STAFF, f"매칭 불확실({m['status']}) — 자동 반환 안 함{note}", alert=True)
    if twin:
        return c.finish(DECISION_STAFF, twin + note, alert=True)
    c.match = m
    c.out.matched_index = m["index"]
    c.out.matched_object = c.detections[m["index"]].get("object_id")
    c.step("매칭 완료", f"점수 {m['score']} · 차이 {m['margin']}")
    if c.talk is not None:
        try:
            c.talk.say(c.req.case_id, "매칭 에이전트", "메인 AI", "reply",
                       f"탑뷰 물건 {len(c.detections)}개 중 {m['index'] + 1}번이 {c.req.item_id} 예요(점수 {m['score']} · 2위와 차이 {m['margin']})")
        except Exception:
            pass
    return False


def lookalike(c: Ctx, picked: dict) -> str:
    """고른 물건(picked 특징)이 찾는 물건만큼 닮은 '다른 보관 중 물건'이 있으면 그 이유 문장, 없으면 빈 문자열.

    사진 특징만으로는 똑같이 생긴 두 물건을 구별할 수 없다 → 엉뚱한 물건을 돌려주지 않도록 직원이 안쪽 특징을 확인한다.
    목록을 못 읽으면(None) 검사할 수 없으므로 역시 자동 반환하지 않는다. 점수는 매칭 부품과 관계없이 같은 규칙으로 잰다.
    """
    others = c.backend.db_list_active()
    if not isinstance(others, list):
        return "닮은 물건 검사 불가(보관 중 물건 목록 읽기 실패) — 자동 반환 안 함"
    target = feature_similarity(c.item.get("features") or {}, picked)
    known = lambda v: isinstance(v, str) and v not in ("", UNKNOWN, NONE)  # noqa: E731
    want_cat = picked.get("category") if known(picked.get("category")) else (c.item.get("features") or {}).get("category")
    twins = []
    for o in others:
        if not isinstance(o, dict) or o.get("item_id") == c.req.item_id:
            continue
        # 11/4 무작위 시험에서 발견: 품목을 보지 않아 흰색 목업폰을 찾을 때 흰색 보조배터리·핸드크림도 '닮은 물건'으로 셌다
        #   품목이 둘 다 알려져 있고 다르면 사진으로 충분히 구별되므로 뺀다(품목을 모르면 지금처럼 검사)
        o_cat = (o.get("features") or {}).get("category")
        if known(want_cat) and known(o_cat) and o_cat != want_cat:
            continue
        s = feature_similarity(o.get("features") or {}, picked)
        if s >= LOOKALIKE_MIN and s >= target - LOOKALIKE_MARGIN:
            twins.append(str(o.get("item_id")))
    if not twins:
        return ""
    return f"닮은 물건 보관 중({', '.join(twins[:3])}) — 사진으로 구별 불가, 직원이 안쪽 특징 확인"


def approach(c: Ctx) -> bool:
    """4. 사전 접근(일반 위치 제어). 로봇에는 작업대 mm 좌표 + 탑뷰 픽셀을 함께 넘긴다(11/4 결정)
    이동 기준은 mm. 픽셀은 로봇 부품이 화면 기준 확인·기록에 쓸 수 있게 참고로만 준다"""
    det = c.detections[c.match["index"]]
    target = det.get("center_mm")
    if not valid_point_mm(target):
        return c.finish(DECISION_STAFF, "작업대 좌표 없음(카메라 보정 안 됨) — 로봇을 움직이지 않음", alert=True)
    if c.talk is not None and c.slot_area is not None:
        # 11/9 로봇팔 에이전트가 메인 AI 를 거쳐 DB 에이전트에게 칸 범위를 묻고 탑뷰 위치와 맞춰 봄 — 다르면 멈춤(더 조심하는 쪽으로만)
        try:
            why = c.talk.robot_check(c.req.case_id, c.req.item_id, target, c.slot_area(c.req.item_id))
        except Exception:
            why = ""
        if why:
            return c.finish(DECISION_STAFF, why, alert=True)
    gpu = getattr(c.backend, "gpu_acquire", None)      # GPU 사용권(11/4): STT·Qwen 이 GPU 를 쓰는 중이면 기다리고, 못 받으면 직원 확인
    if callable(gpu):
        ok, why = gpu("vla")
        if not ok:
            return c.finish(DECISION_STAFF, f"GPU 사용권 없음 — 로봇을 움직이지 않음: {why}", alert=True)
        if not why:                                     # 사용권 기능이 꺼져 있으면(why="꺼짐") 단계로 남기지 않음
            c.step("GPU 사용권 받음")
    if not _set_status(c, "반환 중"):
        return c.finish(DECISION_STAFF, "상태 기록 실패 — 로봇을 움직이지 않음", alert=True)
    px = det.get("center") or []
    r = c.backend.robot_approach([float(target[0]), float(target[1])], [float(v) for v in px])
    if not r["ok"]:
        note = _stop(c)
        return c.finish(DECISION_STOPPED, f"사전 접근 실패: {r['reason']}{note}", alert=True)
    c.step("사전 접근 완료")
    return False


def grasp(c: Ctx) -> bool:
    """5. 근거리 집기(SmolVLA) — 실패하면 1번만 다시"""
    c.grasp_started = True
    for attempt in range(1, MAX_GRASP_ATTEMPTS + 1):
        g = c.backend.robot_grasp()
        v = c.backend.robot_verify_grasp() if g["ok"] else g
        if g["ok"] and v["ok"]:
            c.step("집기 성공", f"{attempt}번째 시도")
            return False
        c.reporter.progress(c.req.case_id, "집기 실패", f"{attempt}번째 시도: {v['reason']}")
        if v.get("reason") == STAFF_STOP_REASON:     # 직원이 정지 버튼을 눌렀으면 다시 집지 않는다
            break
    note = _stop(c)
    why = f"({STAFF_STOP_REASON})" if v.get("reason") == STAFF_STOP_REASON else ""
    return c.finish(DECISION_STOPPED, f"집기 실패{why} — 정지, 직원 호출{note}", alert=True)


def deliver(c: Ctx) -> bool:
    """6. 바구니 전달(일반 위치 제어)"""
    d = c.backend.robot_deliver()
    if not d["ok"]:
        note = _stop(c)
        return c.finish(DECISION_STOPPED, f"바구니 전달 실패: {d['reason']}{note}", alert=True)
    c.step("제출보관함 전달 완료")
    # 11/4: 바구니에 넣은 것 ≠ 분실인이 받은 것. 인계 완료는 직원이 건넨 뒤 직원 화면에서 확인한다
    if not _set_status(c, HANDOVER_WAIT):   # 물건은 이미 전달됨 → 결정은 반환, 기록만 직원이 바로잡음
        return c.finish(DECISION_RETURNED, "제출보관함 전달 완료 · 상태 기록 실패 — 직원 확인", alert=True)
    return c.finish(DECISION_RETURNED, "제출보관함 전달 완료 · 직원 인계 대기(교차 검증)")


STAGES = [("web_gate", web_gate), ("visit_gate", visit_gate), ("shelf_handover", shelf_handover), ("locate", locate),
          ("approach", approach), ("grasp", grasp), ("deliver", deliver)]


def new_ctx(req: ReturnRequest, backend, reporter, reviewer: Reviewer | None = None, consult: Callable | None = None,
            talk=None, slot_area: Callable | None = None) -> Ctx:
    c = Ctx(req, backend, reporter, reviewer, Outcome(req.case_id, DECISION_STAFF, ""), time.perf_counter())
    c.consult, c.talk, c.slot_area = consult, talk, slot_area
    return c


def run_return(req: ReturnRequest, backend, reporter, reviewer: Reviewer | None = None,
               consult: Callable | None = None, talk=None, slot_area: Callable | None = None) -> Outcome:
    """단계를 순서대로 실행(LangGraph 없이). 그래프판은 agents/graph.py — 같은 단계 함수를 쓴다.
    consult: 관제탑 메인 AI(agents/tower_brain.py TowerBrain.consult). None 이면 매칭이 애매할 때 바로 직원 확인"""
    c = new_ctx(req, backend, reporter, reviewer, consult, talk, slot_area)
    for _, stage in STAGES:
        if stage(c):
            break
    if talk is not None:
        try:
            talk.return_done(req.case_id, req.item_id, c.out.decision, c.out.reason)
        except Exception:
            pass
    return c.out
