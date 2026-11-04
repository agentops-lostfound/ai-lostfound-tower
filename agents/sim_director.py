"""가상 시연 연출기 — 디스코드 한 줄로 습득 → 회수 → 찾기 → 반환 → 인계 전체를 돌린다 (LF-29, 11/4).

한줄 설명: 진짜 시연에서 사람(습득자·직원·분실인)과 화면(등록기계·웹·직원 화면)이 하던 일을 대신 해 주는 "연출자".
           단, 관제탑에는 진짜 화면과 **똑같은 입구**(create_item · set_item_features · create_claim · start_return · handover)로만 요청한다.
           → 진짜 화면이 생기면 그 단계만 연출기에서 빼면 된다(관제탑 코드는 그대로).

    습득 신고("서면역 5번 출구 앞에서 검정 카드지갑 주웠어요")
      ① 등록기계 접수  service.create_item       ← 진짜: 등록기계 태블릿(김재민 PR #48)
      ② Qwen 특징     service.set_item_features ← 진짜: 김건태 Qwen 작업(사진)
      ③ 회수·보관함    세계에서 물건을 옮김        ← 진짜: 직원이 옮김(상태 변경 화면 TBD)
    분실 신고("검정 카드지갑 잃어버렸어요, 서면역에서요")
      ④ 후보·확인 질문·예약  service.create_claim  ← 진짜: 분실인 웹(김재민 LF-2·4·6)
      ⑤ 방문 확인 → 반환     service.start_return  ← 진짜: 직원 화면 "반환 시작"
      ⑥ 인계 완료           service.handover      ← 진짜: 직원 화면 "분실인에게 건넴"

- 메시지 끝 꼬리표로 안전 규칙을 보여 줄 수 있다: #집기실패(1번 실패 후 재시도) · #보정실패(로봇 안 움직임)
  · #신분증불일치(반환 거부) · #수동인계(직원 화면 버튼으로 인계)
- 개인정보: 메시지 원문은 저장·전송하지 않는다. 장소 글과 물건 특징만 쓴다(디스코드 보고기의 개인정보 검사도 그대로)
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from datetime import date

from agents.claims import ClaimError, MemoryClaimStore
from agents.contracts import DECISION_RETURNED, NONE, UNKNOWN, public_card
from agents.live import LiveBoard
from agents.service import Conflict, NotFound, RequestError, TowerService, Unavailable
from agents.sim_world import (LOC_BIN, LOC_TRANSIT, MACHINE_STATION, SimRobot, SimTopview, SimWorld, lost_station,
                              parse_place, query_features, sim_qwen, split_tags)

PUBLIC_COMPARE = ("category", "color", "shape", "material")
CANDIDATE_STATUSES = ("등록기계 보관", "회수 중", "본센터 보관")
QUIZ_QUESTIONS = {"visible_text": "물건에 적힌 글자(로고)가 있다면 무엇인가요?",
                  "mark": "물건에 붙은 스티커나 표시가 있다면 어떤 모양인가요?"}


class SimClaimStore(MemoryClaimStore):
    """찾기 요청 저장(메모리) + 없는 물건이면 거절(PostgresClaimStore 와 같은 규칙)."""

    def __init__(self, world: SimWorld):
        super().__init__()
        self.world = world

    def create(self, claim: dict, today: date | None = None) -> dict:
        if claim["item_id"] not in self.world.items:
            raise ClaimError(f"없는 물건: {claim['item_id']}")
        return super().create(claim, today)


def _known(v) -> bool:
    return isinstance(v, str) and v.strip() not in ("", UNKNOWN, NONE)


def _same_text(a: str, b: str) -> bool:
    wa, wb = (set(re.findall(r"[0-9a-z가-힣]+", (s or "").lower())) for s in (a, b))
    wa.discard("sticker"), wb.discard("sticker")
    return bool(wa & wb)


# 화면·메시지용 한국어(저장 값은 Qwen 원문 그대로 — 진짜 Qwen 결과와 같게)
SHOW = {"rectangular": "직사각형", "rectangle": "직사각형", "stick": "막대형", "cylinder": "원통형", "tube": "튜브형",
        "synthetic leather": "합성가죽", "leather": "가죽", "plastic": "플라스틱", "metal": "금속", "fabric": "천"}


def _show(v: str) -> str:
    return ", ".join(SHOW.get(x.strip(), x.strip()) for x in str(v).split(","))


def _summary(feats: dict) -> str:
    pub = public_card({k: v for k, v in feats.items() if k != "confidence"})
    return " · ".join(_show(pub[k]) for k in PUBLIC_COMPARE if _known(pub.get(k))) or "특징 없음"


class SimDirector:
    def __init__(self, service: TowerService, world: SimWorld, board: LiveBoard, auto_handover: bool = True,
                 visit_wait_s: float = 120.0):
        self.svc, self.world, self.board = service, world, board
        self.auto_handover = auto_handover
        self.visit_wait_s = visit_wait_s
        self.pending: dict[str, dict] = {}          # 확인 질문 답을 기다리는 분실 신고
        self._threads: list[threading.Thread] = []

    @property
    def rep(self):
        return self.svc.reporter

    def _spawn(self, fn, *args) -> None:
        t = threading.Thread(target=fn, args=args, daemon=True)
        self._threads = [x for x in self._threads if x.is_alive()] + [t]
        t.start()

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """시험용: 뒤에서 도는 이야기가 끝날 때까지 기다린다."""
        end = time.time() + timeout
        for t in list(self._threads):
            t.join(max(0.0, end - time.time()))
        return not any(t.is_alive() for t in self._threads)

    # ================= 습득 신고 =================
    def found(self, text: str) -> dict:
        clean, tags = split_tags(text)
        machine, place = parse_place(clean)
        if not machine:
            raise RequestError("어느 역에서 주웠는지 알 수 없어요 — 서면·해운대·중앙 중 하나를 넣어 주세요(등록기계가 있는 역)")
        q = sim_qwen(clean)
        if q["category"] == "unknown":
            raise RequestError("무슨 물건인지 알 수 없어요 — 지갑·USB·립밤·모형폰·핸드크림·보조배터리 중 하나를 넣어 주세요")
        sid = self.board.new_story("found", f"습득 신고 · {place}")
        with self.board.bind(sid):
            self.board.stage("intake", "active")
            rec = self.svc.create_item({"machine_id": machine, "place_text": place})       # 진짜 등록기계와 같은 입구
            item_id = rec["item_id"]
            self.board.set_ids(sid, item_id=item_id)
            self.rep.progress(item_id, "등록기계 접수", f"{machine}({MACHINE_STATION[machine]}역) · {place}")
            self.board.stage("intake", "done", item_id)
        self._spawn(self._after_found, sid, item_id, q)
        from agents.vision_adapter import to_features
        return {"story_id": sid, "item_id": item_id, "machine_id": machine, "place_text": place,
                "features": _summary(to_features(q, 0.9)), "received_at": rec["received_at"]}

    def _after_found(self, sid: str, item_id: str, q: dict) -> None:
        w = self.world
        with self.board.bind(sid):
            try:
                self.board.stage("features", "active", "Qwen3-VL-2B(가상) 사진 분석 중")
                w.sleep(2.5)
                self.svc.set_item_features(item_id, {"qwen": q, "confidence": 0.9})          # 진짜 Qwen 작업과 같은 입구
                w.remember_qwen(item_id, q)
                row = w.db_get_item(item_id) or {}
                self.rep.progress(item_id, "Qwen 특징 분석", f"{_summary(row.get('features', {}))} · 비공개 특징은 확인 질문용으로만 저장")
                self.board.stage("features", "done", _summary(row.get("features", {})))

                self.board.stage("collect", "active", "등록기계 → 본센터")
                w.sleep(1.5)
                w.db_set_status(item_id, "회수 중", changed_by="staff")
                w.move(item_id, LOC_TRANSIT)
                self.rep.progress(item_id, "회수 시작", "등록기계 → 본센터(가상 이동)")
                w.sleep(3.0)
                self.board.stage("collect", "done")
                if not w.move(item_id, LOC_BIN):
                    self.rep.alert(item_id, "보관함 칸이 꽉 참 — 직원이 자리 정리", "")
                    self.board.finish(sid, "보관함 칸 부족", False)
                    return
                w.db_set_status(item_id, "본센터 보관", changed_by="staff")
                slot = w.items[item_id]["slot"] + 1
                self.rep.progress(item_id, "보관함 배치", f"공용 보관함 {slot}번 칸 · 탑뷰 카메라 감시 시작")
                self.board.stage("stored", "done", f"{slot}번 칸")
                self.board.finish(sid, f"{item_id} 보관 완료 — 분실 신고가 오면 반환할 수 있음", True)
            except Exception as e:      # 연출 오류는 경보로 보이고 관제탑은 계속 돈다
                self.rep.alert(item_id, f"가상 습득 진행 오류({type(e).__name__})", "")
                self.board.finish(sid, f"진행 오류({type(e).__name__})", False)

    # ================= 분실 신고 =================
    def candidates(self, desc: dict, station: str | None, limit: int = 3) -> list[dict]:
        """분실인 웹 후보 카드 흉내: 공개 특징만으로 닮은 순서(품목이 다르면 제외)."""
        out = []
        with self.world._lock:
            rows = [r for r in self.world.items.values() if r["status"] in CANDIDATE_STATUSES]
        for r in rows:
            rec = self.world._record(r)
            f = rec["features"]
            if desc.get("category") and f.get("category") != desc["category"]:
                continue
            keys = [k for k in PUBLIC_COMPARE if k in desc and _known(f.get(k))]
            score = sum(1 for k in keys if f.get(k) == desc[k]) / len(keys) if keys else 0.0
            if station and MACHINE_STATION.get(r["machine_id"]) == station:
                score += 0.1                                  # 잃어버린 역과 주운 역이 같으면 조금 앞으로
            if score >= 0.5:
                out.append({"item_id": r["item_id"], "score": round(score, 2), "card": _summary(f),
                            "status": r["status"], "station": MACHINE_STATION.get(r["machine_id"], "본센터")})
        out.sort(key=lambda c: (-c["score"], c["item_id"]))
        return out[:limit]

    def _quiz_field(self, item_id: str) -> str | None:
        rec = self.world.db_get_item(item_id) or {}
        f = rec.get("features", {})
        return next((k for k in ("visible_text", "mark") if _known(f.get(k))), None)

    def lost(self, text: str) -> dict:
        clean, tags = split_tags(text)
        desc = query_features(clean)
        if "category" not in desc:
            raise RequestError("무엇을 잃어버렸는지 알 수 없어요 — 지갑·USB·립밤·모형폰·핸드크림·보조배터리 중 하나를 넣어 주세요")
        station = lost_station(clean)
        cands = self.candidates(desc, station)
        if not cands:
            raise RequestError("닮은 습득물이 아직 없어요 — 습득 신고가 먼저 들어와야 해요(또는 색·품목을 다시 확인)")
        pick = cands[0]["item_id"]
        field = self._quiz_field(pick)
        if field and field not in desc:            # 확인 질문(비공개 특징): 분실인이 아직 말하지 않았으면 물어본다
            pid = uuid.uuid4().hex[:8]
            self.pending[pid] = {"desc": desc, "station": station, "cands": cands, "tags": tags, "field": field,
                                 "t": time.time()}
            return {"pending_id": pid, "question": QUIZ_QUESTIONS[field], "candidates": cands}
        return self._claim(desc, station, cands, tags)

    def answer(self, pending_id: str, text: str) -> dict:
        p = self.pending.pop(pending_id, None)
        if p is None:
            raise NotFound("기다리는 확인 질문이 없어요(시간이 지났거나 이미 답함) — 분실 신고를 다시 보내 주세요")
        clean, more = split_tags(text)
        val = clean.strip()
        if val and not re.fullmatch(r"(모름|몰라요|없음|없어요|기억\s*안\s*나요?)", val):
            p["desc"][p["field"]] = val
        return self._claim(p["desc"], p["station"], p["cands"], p["tags"] | more)

    def _quiz(self, item_id: str, desc: dict, station: str | None) -> list[dict]:
        rec = self.world.db_get_item(item_id) or {}
        f = rec.get("features", {})
        quiz = []
        field = self._quiz_field(item_id)
        if field:
            quiz.append({"field": field, "passed": _same_text(desc.get(field, ""), f[field])})
        if station:
            row = self.world.items[item_id]
            quiz.append({"field": "place", "passed": MACHINE_STATION.get(row["machine_id"]) == station
                         or station in (row.get("place_text") or "")})
        if not quiz:
            quiz.append({"field": "color", "passed": desc.get("color") == f.get("color")})
        return quiz

    def _claim(self, desc: dict, station: str | None, cands: list[dict], tags: set[str]) -> dict:
        pick = cands[0]["item_id"]
        quiz = self._quiz(pick, desc, station)
        passed = all(q["passed"] for q in quiz)
        sid = self.board.new_story("lost", f"분실 신고 · {_summary(desc)}")
        with self.board.bind(sid):
            self.board.stage("claim", "active")
            payload = {"consent": True, "name_masked": "분*인", "id_no_masked": "9*****", "id_verified": True,
                       "description": {k: v for k, v in desc.items() if isinstance(v, str)}, "item_id": pick,
                       "quiz": quiz, "visit_date": date.today().isoformat()}
            if station:
                payload["lost_station"] = station
            claim = self.svc.create_claim(payload)                                         # 진짜 분실인 웹과 같은 입구
            cid = claim["claim_id"]
            self.board.set_ids(sid, claim_id=cid, item_id=pick)
            names = ", ".join(q["field"] for q in quiz)
            self.rep.progress(cid, "찾기 요청 접수", f"후보 {len(cands)}개 중 {pick} 선택 · 확인 질문({names}) "
                              f"{'통과' if passed else '미통과'} · 오늘 방문 예약")
            self.board.stage("claim", "done" if passed else "fail", f"{pick} · 확인 질문 {'통과' if passed else '미통과'}")
        self._spawn(self._after_lost, sid, cid, pick, tags)
        return {"story_id": sid, "claim_id": cid, "item_id": pick, "candidates": cands, "quiz_passed": passed}

    def _after_lost(self, sid: str, cid: str, item_id: str, tags: set[str]) -> None:
        w = self.world
        with self.board.bind(sid):
            try:
                self.board.stage("visit", "active", "물건이 보관함에 올 때까지 기다림")
                end = time.time() + self.visit_wait_s
                while not (w.items[item_id]["status"] == "본센터 보관" and w.items[item_id]["loc"] == LOC_BIN):
                    if time.time() > end:
                        self.rep.alert(cid, "물건이 보관함에 없음 — 반환 시작 안 함", f"물건 {item_id}")
                        self.board.finish(sid, "물건이 보관함에 없음", False)
                        return
                    time.sleep(0.3)
                self.board.stage("visit", "active", "분실인 도착 · 직원 확인 중")
                w.sleep(1.0)
                self.rep.progress(cid, "본센터 방문", "분실인 도착 · 직원이 실물 신분증·안쪽 특징 확인(가상)")
                w.sleep(1.5)
                if "grasp_fail" in tags:
                    w.inject(grasp_fail=1)
                if "calib_fail" in tags:
                    w.inject(calib_fail=True)
                payload = {"claim_id": cid, "visitor_id_match": "id_mismatch" not in tags,
                           "inner_feature_ok": True, "staff_confirmed": True}
                out = None
                for _ in range(120):
                    try:
                        out = self.svc.start_return(payload)                              # 진짜 직원 화면과 같은 입구
                        break
                    except Conflict as e:
                        if e.kind != "busy":
                            raise
                        time.sleep(1.0)       # 다른 반환이 로봇을 쓰는 중 → 차례를 기다림
                if out is None:
                    self.rep.alert(cid, "로봇 차례를 2분 동안 못 받음", "")
                    self.board.finish(sid, "로봇 차례 대기 시간 초과", False)
                    return
                self.board.set_ids(sid, case_id=out["case_id"])
                if out["decision"] != DECISION_RETURNED:
                    ko = {"rejected": "반환 안 함", "staff_check": "직원 확인", "stopped": "로봇 정지"}.get(out["decision"], "")
                    self.board.finish(sid, f"{ko}({out['decision']}) — {out['reason']}", False)
                    return
                if not self.auto_handover or "manual_handover" in tags:
                    self.board.stage("handover", "active", "직원 화면에서 '분실인에게 건넴'")
                    self.board.finish(sid, f"바구니 전달 완료 — 직원 화면 /staff 에서 인계 확인({out['case_id']})", True)
                    return
                w.sleep(3.0)
                self.svc.handover(out["case_id"], {"staff_confirmed": True})               # 진짜 직원 화면과 같은 입구
                self.board.finish(sid, f"인계 완료 — {item_id} 를 분실인에게 건넴", True)
            except (RequestError, Conflict, NotFound, Unavailable) as e:
                self.rep.alert(cid, f"가상 반환 진행 중단: {e}", "")
                self.board.finish(sid, f"중단: {e}", False)
            except Exception as e:
                self.rep.alert(cid, f"가상 반환 진행 오류({type(e).__name__})", "")
                self.board.finish(sid, f"진행 오류({type(e).__name__})", False)

    def reset(self) -> dict:
        """세계를 처음 상태로(보관함 시연 물건 4개, 로봇 원점). 찾기·반환 기록 번호는 이어진다(같은 번호 재사용 방지)."""
        w = self.world
        with w._lock:
            w.items.clear()
            w.contacts.clear()
            w.arm.update(x=w.arm["x"], phase="대기", holding=None, stopped=False, target=None)
            w.faults.update(grasp_fail=0, calib_fail=False)
            w.seed()
        SimRobot(w).robot_home()
        self.pending.clear()
        self.rep.progress("SIM", "가상 세계 초기화", "보관함 시연 물건 4개 · 로봇 원점")
        return w.snapshot()


def build_sim_service(env: dict | None = None):
    """TOWER_SIM=1 일 때 관제탑 서비스. 진짜 부품 환경값(TOWER_VISION_FILE 등)이 있으면 그 부품은 진짜로 쓴다."""
    from agents.backends import CompositeBackend
    from agents.gpu_lease import lease_from_env
    from agents.live import LiveReporter
    from agents.matcher_part import matcher_part_from_env
    from agents.tools import MockBackend
    from agents.vision_adapter import vision_part_from_env
    from discord_ops.reporter import Reporter
    env = os.environ if env is None else env

    def num(key, default):
        try:
            return float(str(env.get(key) or default))
        except ValueError:
            return float(default)
    flag = lambda k: str(env.get(k) or "0").strip().lower() in ("1", "true", "yes", "on")  # noqa: E731
    world = SimWorld(speed=num("TOWER_SIM_SPEED", 1.0))
    board = LiveBoard()
    real_vision = vision_part_from_env(env)
    matcher = matcher_part_from_env(env)
    topview = real_vision or SimTopview(world)
    robot = SimRobot(world)

    def factory():
        return CompositeBackend(vision=topview, matcher=matcher, db=world, robot=robot, fallback=MockBackend())
    reviewer = None
    if flag("TOWER_REVIEWER"):
        from agents.llm_reviewer import OllamaReviewer
        reviewer = OllamaReviewer()
    svc = TowerService(factory, LiveReporter(Reporter(dry_run=not flag("TOWER_SEND")), board), reviewer=reviewer,
                       claims=SimClaimStore(world), intake=world, gpu_lease=lease_from_env(env))
    svc.board, svc.world = board, world
    svc.sim = SimDirector(svc, world, board, auto_handover=not flag("TOWER_SIM_MANUAL_HANDOVER"))
    return svc


__all__ = ["SimDirector", "SimClaimStore", "build_sim_service"]
