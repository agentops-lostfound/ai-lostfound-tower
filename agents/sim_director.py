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

- 메시지 끝 꼬리표로 안전 규칙을 보여 줄 수 있다: #집기실패(1번 실패 후 재시도) · #보정실패(로봇 안 움직임) · #흐린촬영(첫 촬영 매칭 애매 → 메인 AI)
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

from agents.claims import ClaimError, MemoryClaimStore, has_pii
from agents.contracts import DECISION_RETURNED, HANDOVER_DONE, NONE, SHOW_KO, UNKNOWN, public_card, show_ko
from agents.live import LiveBoard
from agents.service import Conflict, NotFound, RequestError, TowerService, Unavailable
from agents.sim_world import (LOC_BIN, LOC_TRANSIT, MACHINE_STATION, SimRobot, SimTopview, SimWorld, lost_station,
                              parse_place, query_features, sim_qwen, split_tags)

PUBLIC_COMPARE = ("category", "color", "shape", "material")
CANDIDATE_STATUSES = ("등록기계 보관", "회수 중", "본센터 보관")
QUIZ_QUESTIONS = {"place": "어느 역에서 잃어버리셨나요? (서면·해운대)", "color": "물건 색이 무엇인가요?",
                  "visible_text": "물건에 적힌 글자(로고)가 있다면 무엇인가요?",
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
SHOW = SHOW_KO          # 11/7 contracts 로 옮김(직원 화면과 같은 표)


def _show(v: str) -> str:
    return show_ko(v)


def _summary(feats: dict) -> str:
    pub = public_card({k: v for k, v in feats.items() if k != "confidence"})
    return " · ".join(_show(pub[k]) for k in PUBLIC_COMPARE if _known(pub.get(k))) or "특징 없음"


class SimDirector:
    def __init__(self, service: TowerService, world: SimWorld, board: LiveBoard, auto_handover: bool = True,
                 visit_wait_s: float = 120.0, qwen_wait_s: float = 180.0):
        self.svc, self.world, self.board = service, world, board
        self.qwen_wait_s = qwen_wait_s                  # 11/7 키오스크 사진 → 진짜 Qwen 특징을 기다리는 최대 시간(초)
        self.qwen_wait: dict[str, threading.Event] = {}  # 접수 번호 → 특징이 들어오면 깨움
        self.auto_handover = auto_handover
        self.visit_wait_s = visit_wait_s
        self.pending: dict[str, dict] = {}          # 확인 질문 답을 기다리는 분실 신고
        self.visit_wait: dict[str, str] = {}        # 11/7 웹 신고: 찾기 번호 → 이야기 번호(본센터 키오스크 회수를 기다림)
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
            raise RequestError("어느 역에서 주웠는지 알 수 없어요 — 서면·해운대 중 하나를 넣어 주세요(등록기계가 있는 역)")
        q = sim_qwen(clean)
        if q["category"] == "unknown":
            raise RequestError("무슨 물건인지 알 수 없어요 — 지갑·USB·립밤·모형폰·핸드크림·보조배터리 중 하나를 넣어 주세요")
        if has_pii(place):   # 11/4: 이야기(화면 제목)를 만들기 전에 막는다 — 예전에는 제목에 전화번호가 보이고 이야기가 멈춰 있었다
            raise RequestError("장소에 전화번호 같은 개인정보는 쓰지 마세요(연락처는 등록기계에서 따로 받습니다)")
        sid = self.board.new_story("found", f"습득 신고 · {place}")
        with self.board.bind(sid):
            self.board.stage("intake", "active")
            try:
                rec = self.svc.create_item({"machine_id": machine, "place_text": place})   # 진짜 등록기계와 같은 입구
            except Exception as e:
                self.board.stage("intake", "fail", str(e)[:80])
                self.board.finish(sid, f"접수 실패: {str(e)[:80]}", False)
                raise
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
                self._collect_store(sid, item_id)
            except Exception as e:      # 연출 오류는 경보로 보이고 관제탑은 계속 돈다
                self.rep.alert(item_id, f"가상 습득 진행 오류({type(e).__name__})", "")
                self.board.finish(sid, f"진행 오류({type(e).__name__})", False)

    def _collect_store(self, sid: str, item_id: str) -> None:
        """특징이 채워진 물건: 등록기계 → 본센터 회수 → 보관함 칸(가상 습득·키오스크 습득 공통). 이야기에 묶인 상태에서 부른다"""
        w = self.world
        self.board.stage("collect", "active", "등록기계 → 본센터")
        w.sleep(1.5)
        w.db_set_status(item_id, "회수 중", changed_by="staff")
        w.move(item_id, LOC_TRANSIT)
        self.rep.progress(item_id, "회수 시작", "등록기계 → 본센터(가상 이동)")
        w.sleep(3.0)
        self.board.stage("collect", "done")
        if not w.move(item_id, LOC_BIN):
            self.rep.alert(item_id, "보관함 칸이 꽉 참 — 직원이 자리 정리", "")
            # 11/8 무작위 시험: '회수 중'으로 남아 분실 후보로 계속 뽑히고 120초 뒤 "보관함에 없음"으로 끝났다 → 후보에서 빠지는 상태로
            w.db_set_status(item_id, "반환 보류", changed_by="staff")   # 계약 상태 중 후보에서 빠지고 직원이 정리하는 것
            self.board.finish(sid, "보관함 칸 부족", False)
            return
        w.db_set_status(item_id, "본센터 보관", changed_by="staff")
        slot = w.items[item_id]["slot"] + 1
        self.rep.progress(item_id, "보관함 배치", f"공용 보관함 {slot}번 칸 · 탑뷰 카메라 감시 시작")
        self.board.stage("stored", "done", f"{slot}번 칸")
        self.board.finish(sid, f"{item_id} 보관 완료 — 분실 신고가 오면 반환할 수 있음", True)

    # ================= 11/7 진짜 키오스크 사진 습득(사진 분석만 진짜 Qwen) =================
    def kiosk_found(self, rec: dict) -> str:
        """키오스크 화면에서 사진과 함께 접수된 물건 → 이야기를 열고, 관제탑 PC Qwen 작업자가 특징을 채우면 회수·보관으로 잇는다.
        작업자(tools/intake_qwen_worker.py)가 꺼져 있으면 qwen_wait_s 뒤 '직원 확인' 경보로 끝난다(가짜 특징을 만들지 않음)"""
        item_id = rec["item_id"]
        sid = self.board.new_story("found", f"습득 신고(키오스크) · {rec.get('place_text', '')}"[:60])
        self.qwen_wait[item_id] = threading.Event()
        with self.board.bind(sid):
            self.board.set_ids(sid, item_id=item_id)
            self.board.stage("intake", "done", item_id)
            machine = rec.get("machine_id") or item_id[:1]
            self.rep.progress(item_id, "등록기계 접수", f"{machine}({MACHINE_STATION.get(machine, '')}역) · 사진 촬영 접수")
            self.board.stage("features", "active", "Qwen3-VL 사진 분석 중(관제탑 PC)")
        self._spawn(self._after_kiosk, sid, item_id)
        return sid

    def on_features(self, item_id: str, qwen: dict | None) -> None:
        """특징 저장 주소(/api/kiosk/items/{id}/features)가 불림 → Qwen 원본 기억 + 기다리던 이야기 깨우기"""
        if isinstance(qwen, dict):
            self.world.remember_qwen(item_id, qwen)
        ev = self.qwen_wait.get(item_id)
        if ev is not None:
            ev.set()

    def _after_kiosk(self, sid: str, item_id: str) -> None:
        ev = self.qwen_wait.get(item_id)
        with self.board.bind(sid):
            try:
                got = ev.wait(self.qwen_wait_s) if ev is not None else False
                self.qwen_wait.pop(item_id, None)
                if item_id not in self.world.items:          # 기다리는 동안 가상 세계 초기화
                    self.board.finish(sid, "가상 세계 초기화로 중단", False)
                    return
                row = self.world.db_get_item(item_id) or {}
                feats = row.get("features") or {}
                if not got:
                    self.board.stage("features", "fail", "Qwen 분석 결과 없음 — 작업자(intake_qwen_worker) 확인")
                    self.rep.alert(item_id, "사진 분석 결과가 오지 않음 — 직원이 /admin 에서 확인", "")
                    self.board.finish(sid, f"{item_id} 사진 분석 대기 시간 초과 — 등록기계에 보관 중(직원 확인)", False)
                    return
                if feats.get("category") in (None, UNKNOWN):
                    self.board.stage("features", "fail", "사진으로 물건 종류를 알 수 없음")
                    self.rep.alert(item_id, "물건 종류 확인 불가 — 직원 확인 필요", "")
                    self.board.finish(sid, f"{item_id} 물건 종류 확인 불가 — 등록기계에 보관 중(직원 확인)", False)
                    return
                self.rep.progress(item_id, "Qwen 특징 분석", f"{_summary(feats)} · 비공개 특징은 확인 질문용으로만 저장")
                self.board.stage("features", "done", _summary(feats))
                self._collect_store(sid, item_id)
            except Exception as e:
                self.rep.alert(item_id, f"키오스크 습득 진행 오류({type(e).__name__})", "")
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
            keys = [k for k in PUBLIC_COMPARE if k in desc]
            # 11/4 무작위 시험: 물건 쪽 칸을 모르면 비교에서 빼서, 색 미상 물건이 색이 정확히 맞는 물건과 같은 점수였다 → 모르는 칸은 0.5
            score = (sum(1.0 if f.get(k) == desc[k] else (0.5 if not _known(f.get(k)) else 0.0) for k in keys) / len(keys)
                     if keys else 0.0)
            if station and MACHINE_STATION.get(r["machine_id"]) == station:
                score += 0.1                                  # 잃어버린 역과 주운 역이 같으면 조금 앞으로
            if score >= 0.5:
                out.append({"item_id": r["item_id"], "score": round(score, 2), "card": _summary(f),
                            "status": r["status"], "station": MACHINE_STATION.get(r["machine_id"], "본센터")})
        out.sort(key=lambda c: (-c["score"], c["item_id"]))
        return out[:limit]

    def _quiz_field(self, item_id: str) -> str | None:
        """확인 질문으로 쓸 칸: 비공개 특징(글자·스티커) → 없으면 주운 역(등록기계 물건) → 없으면 색.
        11/4 무작위 시험: 예전에는 색·역을 분실인이 말하지 않으면 묻지도 않고 오답 처리해 반환 거절이 71/80건이었다"""
        rec = self.world.db_get_item(item_id) or {}
        f = rec.get("features", {})
        private = next((k for k in ("visible_text", "mark") if _known(f.get(k))), None)
        if private:
            return private
        if MACHINE_STATION.get(self.world.items.get(item_id, {}).get("machine_id")):
            return "place"
        return "color" if _known(f.get("color")) else None

    @staticmethod
    def _missing(field: str | None, desc: dict, station: str | None) -> bool:
        if field is None:
            return False
        return station is None if field == "place" else field not in desc

    def lost(self, text: str, opts: dict | None = None) -> dict:
        """opts(11/7 분실인 웹): {"visit": "kiosk"} 이면 방문을 자동으로 하지 않고 본센터 키오스크 회수를 기다린다.
        name_masked·id_no_masked 는 웹이 가린 값(키오스크에서 같은 신분 번호를 다시 입력해야 반환 시작)"""
        clean, tags = split_tags(text)
        if has_pii(clean):   # 11/8 웹 무작위 시험: 하이픈 없는 번호(01012345678)가 화면 검사를 지나 그대로 접수됐다
            raise RequestError("분실 신고에 전화번호·주민등록번호 같은 개인정보는 쓰지 마세요")
        desc = query_features(clean)
        if "category" not in desc:
            raise RequestError("무엇을 잃어버렸는지 알 수 없어요 — 지갑·USB·립밤·모형폰·핸드크림·보조배터리 중 하나를 넣어 주세요")
        return self._next(desc, lost_station(clean), tags, set(), opts or {})

    def _next(self, desc: dict, station: str | None, tags: set[str], asked: set[str], opts: dict | None = None) -> dict:
        """후보 고르기 → (필요하면 질문) → 찾기 요청. 질문은 칸마다 한 번만 한다.
        11/4 무작위 시험: 색을 말하지 않으면 같은 점수 후보 중 번호순 첫 물건을 마음대로 골랐다 → 먼저 색을 물어 좁힌다"""
        cands = self.candidates(desc, station)
        if not cands:
            raise RequestError("닮은 습득물이 아직 없어요 — 습득 신고가 먼저 들어와야 해요(또는 색·품목을 다시 확인)")
        ties = [c for c in cands if c["score"] == cands[0]["score"]]
        if len(ties) > 1 and "color" not in desc and "color" not in asked:
            return self._ask("color", desc, station, tags, asked, cands, "후보가 여러 개예요. 물건 색이 무엇인가요?", opts)
        if len(ties) > 1 and station is None and "place" not in asked and any(c["station"] != "본센터" for c in ties):
            return self._ask("place", desc, station, tags, asked, cands, "후보가 아직 여러 개예요. " + QUIZ_QUESTIONS["place"], opts)
        if len(ties) > 1:                                   # 겉모습으로 못 가르면 비공개 특징(글자·스티커)으로 가른다
            priv = {c["item_id"]: self._quiz_field(c["item_id"]) for c in ties}
            pf = next((f for f in ("visible_text", "mark") if f in priv.values()), None)
            if pf and pf not in desc and pf not in asked:
                return self._ask(pf, desc, station, tags, asked, cands, "후보가 아직 여러 개예요. " + QUIZ_QUESTIONS[pf], opts)
            ties = self._narrow(ties, desc, asked)
            if len(ties) > 1:                               # 그래도 못 가르면 자동으로 고르지 않는다(안전 규칙)
                return self._staff_pick(desc, ties)
            cands = ties + [c for c in cands if c not in ties]
        field = self._quiz_field(cands[0]["item_id"])
        if self._missing(field, desc, station) and field not in asked:   # 확인 질문: 아직 말하지 않은 칸이면 먼저 묻는다
            return self._ask(field, desc, station, tags, asked, cands, QUIZ_QUESTIONS[field], opts)
        return self._claim(desc, station, cands, tags, opts)

    def _narrow(self, ties: list[dict], desc: dict, asked: set[str]) -> list[dict]:
        """비공개 특징 답으로 동점 후보 줄이기. 글자를 말했으면 그 글자가 있는 후보, '모름·없음'이면 글자 없는 후보."""
        out = []
        for c in ties:
            f = (self.world.db_get_item(c["item_id"]) or {}).get("features", {})
            said = [k for k in ("visible_text", "mark") if _known(desc.get(k))]   # '스티커 없음' 같은 값은 가르는 데 쓰지 않음
            if said:
                if all(_known(f.get(k)) and _same_text(desc[k], f[k]) for k in said):
                    out.append(c)
                continue
            if any(k in asked for k in ("visible_text", "mark")):
                if not any(_known(f.get(k)) for k in ("visible_text", "mark")):
                    out.append(c)
            else:
                out.append(c)
        if not out and any(_known(desc.get(k)) for k in ("visible_text", "mark")):
            return ties[:1]          # 말한 글자·표시가 어느 후보와도 맞지 않음 → 그대로 확인 질문으로(미통과 → 반환 안 함)
        return out or ties

    def _staff_pick(self, desc: dict, ties: list[dict]) -> dict:
        """후보를 사진·답으로 구별할 수 없음 → 찾기 요청을 자동으로 만들지 않고 본센터 직원이 후보를 함께 확인(로봇 안 움직임)."""
        sid = self.board.new_story("lost", f"분실 신고 · {_summary(desc)}")
        ids = ", ".join(c["item_id"] for c in ties[:3])
        self.board.stage("claim", "fail", f"후보 {len(ties)}개 구별 불가: {ids}", story_id=sid)
        self.rep.alert("SIM", f"후보 {len(ties)}개를 구별할 수 없음 — 자동 반환 안 함", f"후보 {ids} · 방문 때 직원이 안쪽 특징 확인")
        self.board.finish(sid, f"직원 확인(staff_check) — 후보 {len(ties)}개를 구별할 수 없어 방문 때 직원이 확인", False)
        return {"story_id": sid, "staff": True, "candidates": ties}

    def _ask(self, field, desc, station, tags, asked, cands, question, opts=None) -> dict:
        pid = uuid.uuid4().hex[:8]
        self.pending[pid] = {"desc": desc, "station": station, "tags": tags, "field": field,
                             "asked": asked | {field}, "t": time.time(), "opts": opts or {}}
        return {"pending_id": pid, "question": question, "candidates": cands}

    def answer(self, pending_id: str, text: str) -> dict:
        p = self.pending.pop(pending_id, None)
        if p is None:
            raise NotFound("기다리는 확인 질문이 없어요(시간이 지났거나 이미 답함) — 분실 신고를 다시 보내 주세요")
        clean, more = split_tags(text)
        val = clean.strip()
        if has_pii(val):
            raise RequestError("답에 전화번호 같은 개인정보는 쓰지 마세요 — 분실 신고를 다시 보내 주세요")
        if val and not re.fullmatch(r"(모름|몰라요|없음|없어요|확인\s*불가|기억\s*안\s*나요?)", val):
            if p["field"] == "place":
                p["station"] = lost_station(val) or p["station"]
            elif p["field"] == "color":
                color = query_features(val).get("color")
                if color:
                    p["desc"]["color"] = color
            else:
                p["desc"][p["field"]] = val
        return self._next(p["desc"], p["station"], p["tags"] | more, p["asked"], p.get("opts") or {})

    def _quiz(self, item_id: str, desc: dict, station: str | None) -> list[dict]:
        rec = self.world.db_get_item(item_id) or {}
        f = rec.get("features", {})
        quiz = []
        field = self._quiz_field(item_id)
        if field in ("visible_text", "mark"):
            quiz.append({"field": field, "passed": _same_text(desc.get(field, ""), f[field])})
        if station or field == "place":
            row = self.world.items[item_id]
            quiz.append({"field": "place", "passed": station is not None and (
                MACHINE_STATION.get(row["machine_id"]) == station or station in (row.get("place_text") or ""))})
        if not quiz or field == "color":
            quiz.append({"field": "color", "passed": desc.get("color") == f.get("color")})
        return quiz

    def _claim(self, desc: dict, station: str | None, cands: list[dict], tags: set[str], opts: dict | None = None) -> dict:
        opts = opts or {}
        pick = cands[0]["item_id"]
        quiz = self._quiz(pick, desc, station)
        passed = all(q["passed"] for q in quiz)
        sid = self.board.new_story("lost", f"분실 신고 · {_summary(desc)}")
        with self.board.bind(sid):
            self.board.stage("claim", "active")
            payload = {"consent": True, "name_masked": opts.get("name_masked") or "분*인",
                       "id_no_masked": opts.get("id_no_masked") or "9*****", "id_verified": True,
                       "description": {k: v for k, v in desc.items() if isinstance(v, str)}, "item_id": pick,
                       "quiz": quiz, "visit_date": date.today().isoformat()}
            if station:
                payload["lost_station"] = station
            try:
                claim = self.svc.create_claim(payload)                                     # 진짜 분실인 웹과 같은 입구
            except Exception as e:
                # 11/8 무작위 시험: 이미 찾기 요청이 있는 물건(Conflict)이면 이야기가 'claim 진행 중'으로 영원히 남았다
                self.board.stage("claim", "fail", f"{pick} · {getattr(e, 'kind', type(e).__name__)}")
                self.board.finish(sid, f"찾기 요청 안 됨 — {e}", False)
                raise RequestError(str(e) or "찾기 요청을 만들지 못했어요") from e
            cid = claim["claim_id"]
            self.board.set_ids(sid, claim_id=cid, item_id=pick)
            names = ", ".join(q["field"] for q in quiz)
            self.rep.progress(cid, "찾기 요청 접수", f"후보 {len(cands)}개 중 {pick} 선택 · 확인 질문({names}) "
                              f"{'통과' if passed else '미통과'} · 오늘 방문 예약")
            self.board.stage("claim", "done" if passed else "fail", f"{pick} · 확인 질문 {'통과' if passed else '미통과'}")
        self._spawn(self._after_lost, sid, cid, pick, tags, opts.get("visit") == "kiosk")
        return {"story_id": sid, "claim_id": cid, "item_id": pick, "candidates": cands, "quiz_passed": passed,
                "visit": "kiosk" if opts.get("visit") == "kiosk" else "auto"}

    def _after_lost(self, sid: str, cid: str, item_id: str, tags: set[str], wait_kiosk: bool = False) -> None:
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
                if wait_kiosk:                 # 11/7 웹 신고: 본센터 키오스크 '물건 찾으러 왔어요'에서 찾기 번호 입력을 기다림
                    self.board.stage("visit", "active", "본센터 방문 대기 · 키오스크 회수 탭에서 찾기 번호 입력")
                    self.rep.progress(cid, "본센터 방문 대기", "분실인이 부산역 본센터 키오스크에서 찾기 번호·신분 번호를 입력하면 반환 시작")
                    self.visit_wait[cid] = sid
                    return
                self.board.stage("visit", "active", "분실인 도착 · 직원 확인 중")
                w.sleep(1.0)
                self.rep.progress(cid, "본센터 방문", "분실인 도착 · 직원이 실물 신분증·안쪽 특징 확인(가상)")
                w.sleep(1.5)
                if "grasp_fail" in tags:
                    w.inject(grasp_fail=1)
                if "calib_fail" in tags:
                    w.inject(calib_fail=True)
                if "blur_once" in tags:
                    w.inject(blur=True)
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
                    # 11/8 무작위 시험: 'active' 로 두면 finish 가 'done' 으로 바꿔 직원 확인 전인데 인계 완료로 보였다
                    self.board.stage("handover", "todo", "직원 화면에서 '분실인에게 건넴'")
                    self.board.finish(sid, f"제출보관함 전달 완료 — 직원 화면 /staff 에서 교차 검증({out['case_id']})", True)
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

    def kiosk_return(self, payload: dict) -> dict:
        """11/7 본센터 키오스크 회수(가상 시연): 웹 신고 이야기에 단계를 이어 붙인 뒤 진짜와 같은 입구(service.kiosk_return)로.
        반환이 끝나면 물건은 제출보관함 — 인계는 직원 교차 검증(/staff)이 한다(자동 인계 안 함)"""
        cid = payload.get("claim_id") if isinstance(payload, dict) else None
        sid = self.visit_wait.get(cid) if isinstance(cid, str) else None
        if sid is None:
            return self.svc.kiosk_return(payload)
        with self.board.bind(sid):
            self.board.stage("visit", "active", "본센터 키오스크 · 본인 확인 중")
            try:
                out = self.svc.kiosk_return(payload)
            except RequestError as e:      # 신분 번호 틀림 등 — 계속 기다림
                self.board.stage("visit", "active", f"본센터 방문 대기 · 다시 입력 필요({e})")
                raise
            except Conflict as e:
                if e.kind == "locked":
                    self.visit_wait.pop(cid, None)
                    self.board.finish(sid, "신분 번호를 여러 번 틀려 역무실로 안내", False)
                raise
            self.visit_wait.pop(cid, None)
            self.board.stage("visit", "done", "본센터 키오스크 본인 확인 완료")
            self.board.set_ids(sid, case_id=out.get("case_id"))
            if out.get("decision") != DECISION_RETURNED:
                ko = {"rejected": "반환 안 함", "staff_check": "직원 확인", "stopped": "로봇 정지"}.get(out.get("decision"), "")
                self.board.finish(sid, f"{ko}({out.get('decision')}) — {out.get('reason')}", False)
                return out
            self.board.stage("handover", "todo", "제출보관함 · 직원 교차 검증 대기(/staff)")
            self.board.finish(sid, f"제출보관함 도착 — 직원 교차 검증 후 인계({out.get('case_id')})", True)
            return out

    def on_verify(self, case_id: str, result: dict) -> None:
        """11/7 직원 교차 검증 결과를 그 반환 이야기의 '인계 완료' 단계에 반영(분실인 웹 진행 상황이 끝까지 보이게)"""
        for sid, st in list(self.board.stories.items()):
            if st.get("ids", {}).get("case_id") != case_id:
                continue
            if result.get("result") == HANDOVER_DONE:
                self.board.stage("handover", "done", "직원 교차 검증 통과 · 분실인에게 건넴", story_id=sid)
                self.board.finish(sid, f"인계 완료 — {result.get('item_id')} 를 분실인에게 건넴", True)
            else:
                self.board.stage("handover", "fail", "직원 교차 검증 불일치 · 반환 보류", story_id=sid)
                self.board.finish(sid, f"반환 보류 — 교차 검증 불일치({result.get('reason') or '확인 필요'})", False)
            return

    def reset(self) -> dict:
        """세계를 처음 상태로(보관함 시연 물건 5개, 로봇 원점). 찾기·반환 기록 번호는 이어진다(같은 번호 재사용 방지).
        11/7: 보관함 정답지(svc.storage) 칸을 먼저 비운 뒤 채운다 — 예전 예약이 남아 있으면 새 시연 물건이 엉뚱한 칸으로 감"""
        w = self.world
        waiting, self.qwen_wait = self.qwen_wait, {}    # 11/7 사진 분석을 기다리던 키오스크 이야기는 깨워서 '초기화로 중단'
        for ev in waiting.values():
            ev.set()
        st = getattr(self.svc, "storage", None)
        if st is not None:                              # 정답지 칸 비우기(세계 잠금 밖 — 정답지는 세계를 읽음)
            for sec in st.layout()["sections"]:
                for sl in sec["slots"]:
                    if sl.get("item"):
                        try:
                            st.release(slot_id=sl["slot_id"])
                        except Exception:
                            pass
        hooks = (w.on_bin, w.reserved)
        with w._lock:
            w.on_bin = w.reserved = None                # 잠금 안에서 정답지를 부르지 않게(교착 방지) — 아래에서 맞춤
            try:
                w.items.clear()
                w.contacts.clear()
                w.arm.update(x=w.arm["x"], phase="대기", holding=None, stopped=False, target=None)
                w.faults.update(grasp_fail=0, calib_fail=False, blur=False)
                w.seed()
            finally:
                w.on_bin, w.reserved = hooks
        SimRobot(w).robot_home()
        self.pending.clear()
        self.visit_wait.clear()
        if w.on_bin:                                    # 시연 물건 칸 → 정답지
            for r in list(w.items.values()):
                sid = w.slot_id_of(r["item_id"])
                if sid:
                    w.on_bin(r["item_id"], sid)
        self.rep.progress("SIM", "가상 세계 초기화", f"보관함 시연 물건 {len(w.items)}개 · 로봇 원점")
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
    svc.sim = SimDirector(svc, world, board, auto_handover=not flag("TOWER_SIM_MANUAL_HANDOVER"),
                          qwen_wait_s=num("TOWER_SIM_QWEN_WAIT", 180))
    link_storage(svc, world)
    from agents.tower_brain import build_from_env     # 11/8 관제탑 메인 AI(.env TOWER_BRAIN=1 일 때만)
    svc.brain = build_from_env(slot_lookup=lambda item_id: sim_slot_area(svc, world, item_id))
    return svc


def sim_slot_area(svc: TowerService, world: SimWorld, item_id: str) -> dict | None:
    """메인 AI 보관 칸 에이전트용(가상): 정답지의 칸 번호 + 가상 작업대에서 그 칸의 위치(±45mm)를 구역 좌표로.
    실제 보관함은 /storage 화면에서 구역 좌표(bounds_mm)를 넣어야 위치로 후보를 가릴 수 있다"""
    from agents.sim_world import SLOT_IDS, SLOTS_MM
    area = svc.slot_area(item_id) or {}
    sid = area.get("slot_id") or world.slot_id_of(item_id)
    if not sid:
        return None
    if not area.get("bounds_mm") and sid in SLOT_IDS:
        x, y = SLOTS_MM[SLOT_IDS.index(sid)]
        area = {"slot_id": sid, "bounds_mm": [x - 45, y - 45, x + 45, y + 45]}
    return {"slot_id": sid, "bounds_mm": area.get("bounds_mm")}


def link_storage(svc: TowerService, world: SimWorld) -> None:
    """11/7 가상 작업대 ↔ 보관함 정답지(svc.storage) 맞추기 — 화면(/live·/admin)과 보관 화면(/storage)이 같은 칸을 보이게.
    - 가상 세계가 물건을 칸에 넣으면 → 정답지에도 같은 칸(품목이 다른 행이면 override)
    - 정답지가 예약한 칸(반환 중·보류 물건의 원래 칸)은 가상 세계가 새 물건에 주지 않음
    - 직원이 보관 화면에서 칸을 고르면 → 가상 세계도 그 칸으로"""
    st = svc.storage

    def reserved():
        lay = st.layout()
        return {sl["slot_id"]: (sl.get("item") or {}).get("item_id") for sec in lay["sections"] for sl in sec["slots"]
                if sl.get("item")}

    def on_bin(item_id, slot_id):
        try:
            st.assign(item_id, slot_id, override_category=True, by="sim", arrive=True)   # 회수 중 → 칸 도착(본센터 보관)
        except Exception:
            pass
    world.reserved, world.on_bin = reserved, on_bin
    orig_place = st.place

    def place(item_id, slot_id, override_category=False):
        out = orig_place(item_id, slot_id, override_category)
        world.put(item_id, slot_id)
        return out
    st.place = place
    for r in list(world.items.values()):              # 시작할 때 이미 칸에 있는 시연 물건
        sid = world.slot_id_of(r["item_id"])
        if sid:
            on_bin(r["item_id"], sid)


__all__ = ["SimDirector", "SimClaimStore", "build_sim_service"]
