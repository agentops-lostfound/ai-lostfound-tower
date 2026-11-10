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
from agents.contracts import (DECISION_RETURNED, HANDOVER_DONE, NONE, SHOW_KO, UNKNOWN, active_category_text,
                              inactive_category_message, is_active_category, public_card, show_ko)
from agents.live import LiveBoard
from agents.service import Conflict, NotFound, RequestError, TowerService, Unavailable
from agents.sim_world import (LOC_BIN, LOC_GRIPPER, LOC_KIOSK, LOC_SHELF, LOC_STAFF, LOC_TRANSIT, MACHINE_STATION, SimRobot, SimTopview,
                              SimWorld, lost_station, parse_place, query_features, sim_qwen, slot_rows, split_tags)

PUBLIC_COMPARE = ("category", "color", "shape", "material")
# 11/9 버튼을 바꿔 누른 경우(사용자 실측: "파란색 폰 잃어버렸어요"로 '습득 신고' → "어느 역에서 주웠는지 알 수 없어요").
# 한줄 설명: 글에 반대쪽 말(잃어버·주웠)만 있고 제 쪽 말이 없으면, 엉뚱한 오류 대신 맞는 버튼을 알려 준다
LOST_SAY = re.compile(r"잃어버|잃었|잊어버|분실했|분실한|분실해|두고\s*내|놓고\s*내")
FOUND_SAY = re.compile(r"주웠|주운|주워|습득했|습득한|발견했|떨어져\s*있|놓여\s*있")
TO_LOST = "잃어버린 물건이면 '분실 신고'를 눌러 주세요 — 습득 신고는 주운 물건을 맡길 때 써요"
TO_FOUND = "주운 물건이면 '습득 신고'를 눌러 주세요 — 분실 신고는 잃어버린 물건을 찾을 때 써요"
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


# 11/9 채점표(evaluation/chat_eval.py)에서 찾음: 검정 지갑 분실 신고가 갈색 지갑 후보로 찾기 번호가 됐다(품목 1점 + 색 0점 = 0.5 로 문턱 통과).
# 사진으로 본 색은 비슷한 색끼리 헷갈릴 수 있어(검정↔남색, 흰색↔회색) 그 묶음 안에서는 후보로 남기고, 아주 다른 색만 뺀다
NEAR_COLORS = ({"검정", "남색", "회색"}, {"흰색", "회색", "은색", "베이지"}, {"갈색", "베이지", "주황"}, {"파랑", "남색", "하늘"},
               {"빨강", "분홍", "주황"}, {"초록", "연두"}, {"노랑", "주황", "베이지"})


def _far_color(a, b) -> bool:
    """둘 다 아는 색인데 비슷한 색 묶음에도 같이 없으면 True(후보에서 뺌)"""
    if not (_known(a) and _known(b)) or a == b:
        return False
    return not any(a in g and b in g for g in NEAR_COLORS)


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
        # 11/9 칸 대기: 물건 번호 → 습득 이야기 번호(칸이 비면 그 이야기를 이어서 회수)
        self.wait_story: dict[str, str] = {}
        # 11/9 분실인이 먼저 신고(닮은 습득물이 아직 없음) → 대기 번호로 받아 두고, 습득물이 들어오면 찾기 요청으로 잇는다(정연우 검토)
        self.waiting_lost: dict[str, dict] = {}
        self._wait_lock = threading.Lock()
        self._wait_no = 0
        self._drain_lock = threading.Lock()
        self._drain_again = False
        # 11/10 직원 단추([본센터로 회수]·[접수 취소]): 지금 이야기가 진행 중인 물건(겹쳐 움직이지 않게) · 취소한 물건
        self._flowing: set[str] = set()
        self._flow_lock = threading.Lock()
        self.cancelled: set[str] = set()
        world.on_freed = self.kick_wait

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
        while True:                 # 11/9 기다리는 동안 새로 생긴 이야기(칸 대기 자동 회수)도 끝날 때까지
            alive = [t for t in list(self._threads) if t.is_alive()]
            if not alive:
                return True
            if time.time() >= end:
                return False
            for t in alive:
                t.join(max(0.0, end - time.time()))

    # ================= 습득 신고 =================
    def found(self, text: str) -> dict:
        clean, tags = split_tags(text)
        if LOST_SAY.search(clean) and not FOUND_SAY.search(clean):
            raise RequestError(TO_LOST)
        machine, place = parse_place(clean)
        if not machine:
            raise RequestError("어느 역에서 주웠는지 알 수 없어요 — 서면·해운대 중 하나를 넣어 주세요(등록기계가 있는 역)")
        q = sim_qwen(clean)
        if q["category"] == "unknown":
            raise RequestError(f"무슨 물건인지 알 수 없어요 — {active_category_text()} 중 하나를 넣어 주세요")
        from agents.vision_adapter import CATEGORY as QWEN_TO_KO
        if not is_active_category(QWEN_TO_KO.get(q["category"])):   # 11/9 립밤 등 운영하지 않는 품목은 가상 세계에 만들지 않음
            raise RequestError(inactive_category_message(QWEN_TO_KO.get(q["category"], q["category"])))
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
                self._talk_found(item_id, row)
                if self.waiting_lost:                  # 11/9 먼저 들어온 분실 신고 중 닮은 것이 있으면 찾기 요청으로 잇기
                    self._spawn(self._match_waiting, item_id)
                self._collect_store(sid, item_id)
            except Exception as e:      # 연출 오류는 경보로 보이고 관제탑은 계속 돈다
                self.rep.alert(item_id, f"가상 습득 진행 오류({type(e).__name__})", "")
                self.board.finish(sid, f"진행 오류({type(e).__name__})", False)

    @property
    def talk(self):
        return getattr(self.svc, "talk", None)

    def _talk_found(self, item_id: str, row: dict) -> None:
        """11/9 에이전트 대화: 키오스크 AI → 메인 AI → DB 에이전트 등록 확인(채점·도움 포함). 실패해도 습득 흐름은 계속"""
        if self.talk is None:
            return
        try:
            place = (self.world.items.get(item_id) or {}).get("place_text") or row.get("place_text") or ""
            self.talk.found_registered(item_id, row, place)
        except Exception:
            pass

    def _talk_slot(self, item_id: str, cat, slot, wait_no=None) -> None:
        if self.talk is None:
            return
        try:
            allowed = slot_rows().get((slot or "").split("-")[0]) if slot else None
            self.talk.slot_reserved(item_id, item_id, cat, slot, allowed, wait_no)
            if not slot:
                self.talk.flush(item_id, f"습득 {item_id} 에이전트 대화(칸 대기)")
        except Exception:
            pass

    @staticmethod
    def _group(category: str | None) -> tuple:
        """품목이 들어갈 행 묶음(11/9 015: 휴대폰 R1 · 지갑 R2 · 보조배터리 R3 · 핸드크림·USB R4). 같은 묶음끼리만 칸 대기 순서를 지킨다"""
        rows = slot_rows()
        return tuple(sorted(code for code, allowed in rows.items() if category in allowed or not allowed))

    def _category(self, item_id: str) -> str | None:
        cat = (self.world.items.get(item_id) or {}).get("category")
        return None if cat in (None, UNKNOWN) else cat

    def _collect_store(self, sid: str, item_id: str) -> None:
        """특징이 채워진 물건: (칸 확인) → 등록기계 → 본센터 회수 → 보관함 칸(가상 습득·키오스크 습득 공통). 이야기에 묶인 상태에서 부른다.
        11/9 보관함이 꽉 찼을 때: 회수하기 전에 그 품목이 들어갈 빈 칸을 잡아 둔다. 없으면(또는 같은 묶음에 먼저 기다리는 물건이 있으면)
        회수하지 않고 등록기계에 둔 채 '칸 대기' + 직원 알림(물건 번호만). 칸이 비면 kick_wait 가 먼저 온 순서대로 이어서 회수한다"""
        w = self.world
        cat = self._category(item_id)
        slot = w.reserved_for(item_id)
        if slot is None:
            mine = self._group(cat)
            ahead = [x for x in list(w.wait_queue) if x != item_id and self._group(self._category(x)) == mine]
            slot = None if ahead else w.reserve_slot(item_id, cat)
        if slot is None:
            pos, mine = w.add_wait(item_id), self._group(cat)
            n = sum(1 for x in list(w.wait_queue)[:pos] if self._group(self._category(x)) == mine)   # 같은 묶음 안 순서
            self.wait_story[item_id] = sid
            self._talk_slot(item_id, cat, None, n)
            self.svc.notify_slot_wait(item_id, n)       # 경보가 지금 단계를 '실패'로 칠하므로 그 뒤에 '진행(대기)'로 다시 칠함
            self.board.stage("collect", "active", f"칸 대기 {n}번째 — 맞는 빈 칸이 없어 등록기계에 보관")
            return
        self._talk_slot(item_id, cat, slot)
        self.board.stage("collect", "active", f"등록기계 → 본센터 · {slot} 칸 확보")
        w.sleep(1.5)
        w.db_set_status(item_id, "회수 중", changed_by="staff")
        w.move(item_id, LOC_TRANSIT)
        self.rep.progress(item_id, "회수 시작", f"등록기계 → 본센터(가상 이동) · {slot} 칸 확보")
        w.sleep(3.0)
        self.board.stage("collect", "done")
        if w.items.get(item_id, {}).get("loc") == LOC_SHELF:     # 이동 중에 직원이 선반으로 옮김
            self.board.stage("stored", "done", "직원 보관 선반")
            self.board.finish(sid, f"{item_id} 직원 보관 선반에 보관 — 반환은 직원이 건넴", True)
            return
        if not w.move(item_id, LOC_BIN):                         # 잡아 둔 칸이 있어 보통은 생기지 않음(가상 세계 초기화 등)
            self.rep.alert(item_id, "보관 칸을 잃음 — 직원이 직원 보관 선반에 두기", "")
            w.move(item_id, LOC_STAFF)                           # 직원 손 — 보관함 화면 도착 대기(본센터)에 보임
            self.board.finish(sid, "보관 칸 없음 — 직원 확인", False)
            return
        w.db_set_status(item_id, "본센터 보관", changed_by="staff")
        sid_slot = w.slot_id_of(item_id) or "?"
        self.rep.progress(item_id, "보관함 배치", f"공용 보관함 {sid_slot} 칸 · 탑뷰 카메라 감시 시작")
        self.board.stage("stored", "done", f"{sid_slot} 칸")
        if self.talk is not None:
            try:
                self.talk.stored(item_id, item_id, sid_slot)
            except Exception:
                pass
        self.board.finish(sid, f"{item_id} 보관 완료({sid_slot}) — 분실 신고가 오면 반환할 수 있음", True)

    def _claimed_to_shelf(self, cid: str, item_id: str) -> None:
        """찾는 사람이 생긴 칸 대기 물건: 등록기계 → 본센터 회수 → 직원 보관 선반(정답지도 선반으로)"""
        w = self.world
        with w._lock:
            if item_id in w.wait_queue:
                w.wait_queue.remove(item_id)
        self.board.stage("visit", "active", "칸 대기 물건 — 찾는 분이 있어 먼저 회수해 직원 보관 선반에 둠")
        self.rep.progress(cid, "칸 대기 물건 먼저 회수", f"물건 {item_id} · 보관함이 꽉 차 직원 보관 선반으로(직원이 건넴)")
        w.db_set_status(item_id, "회수 중", changed_by="staff")
        w.move(item_id, LOC_TRANSIT)
        w.sleep(3.0)
        try:
            self.svc.move_to_shelf({"item_id": item_id})    # 정답지·세계 모두 선반으로(직원 보관 선반 S-n)
        except Exception:
            w.to_shelf(item_id)
        w.db_set_status(item_id, "본센터 보관", changed_by="staff")
        story = self.wait_story.pop(item_id, None)
        if story:
            self.board.finish(story, f"{item_id} 찾는 분이 있어 직원 보관 선반으로 회수 — 반환은 직원이 건넴", True)

    # ----- 11/9 칸 대기 → 칸이 비면 자동 회수 -----
    def kick_wait(self) -> None:
        """칸이 비었을 수 있음(인계 완료·칸 비우기·선반 이동) → 뒤에서 칸 대기 물건 회수를 시도"""
        if self.world.wait_queue:
            self._spawn(self.drain_wait)

    def drain_wait(self) -> list[str]:
        """칸 대기 줄을 먼저 온 순서대로 보며, 맞는 빈 칸이 생긴 물건을 회수한다(묶음마다 앞 물건이 막히면 뒤 물건도 기다림).
        돌려주는 값 = 이번에 회수를 시작한 물건 번호"""
        if not self._drain_lock.acquire(blocking=False):
            self._drain_again = True                # 지금 도는 회수가 끝나면 한 번 더
            return []
        started = []
        try:
            while True:
                self._drain_again = False
                w, blocked = self.world, set()
                for item_id in list(w.wait_queue):
                    row = w.items.get(item_id)
                    if row is None or row["loc"] != LOC_KIOSK or row["status"] != "등록기계 보관":
                        with w._lock:               # 선반으로 옮겼거나 초기화됨 → 줄에서 뺌
                            if item_id in w.wait_queue:
                                w.wait_queue.remove(item_id)
                        continue
                    cat = self._category(item_id)
                    g = self._group(cat)
                    if g in blocked:
                        continue
                    if w.reserve_slot(item_id, cat) is None:
                        blocked.add(g)
                        continue
                    started.append(item_id)
                    self._spawn(self._resume_collect, item_id)
                if not self._drain_again:
                    return started
        finally:
            self._drain_lock.release()

    def _resume_collect(self, item_id: str) -> None:
        if not self._flow_begin(item_id):               # 직원이 방금 [본센터로 회수]를 눌러 이미 움직이는 중
            return
        sid = self.wait_story.pop(item_id, None) or self.board.new_story("found", f"칸 대기 회수 · {item_id}")
        with self.board.bind(sid):
            try:
                self.rep.progress(item_id, "칸 생김 · 자동 회수", "칸 대기 물건을 먼저 온 순서대로 회수")
                self._collect_store(sid, item_id)
            except Exception as e:
                self.rep.alert(item_id, f"칸 대기 회수 진행 오류({type(e).__name__})", "")
                self.board.finish(sid, f"진행 오류({type(e).__name__})", False)
            finally:
                self._flow_end(item_id)

    # ----- 11/10 직원 단추: [본센터로 회수] · [접수 취소] (통합 시연 화면) -----
    def _flow_begin(self, item_id: str) -> bool:
        with self._flow_lock:
            if item_id in self._flowing:
                return False
            self._flowing.add(item_id)
            return True

    def _flow_end(self, item_id: str) -> None:
        with self._flow_lock:
            self._flowing.discard(item_id)

    def collect_now(self, item_id: str) -> dict:
        """직원이 [본센터로 회수]를 누름: 등록기계에 남아 있는 물건(칸 대기 · 사진 분석이 늦게 끝난 건)을 지금 회수한다.
        맞는 빈 칸이 있으면 그 칸에, 없으면 직원 보관 선반에 둔다. → {"ok", "reason"}. 뒤에서 진행되고 화면은 이야기로 보인다"""
        w = self.world
        row = w.items.get(item_id)
        if row is None:
            return {"ok": False, "code": "not_found", "reason": "없는 물건 번호예요"}
        if row.get("status") != "등록기계 보관" or row.get("loc") != LOC_KIOSK:
            return {"ok": False, "code": "state", "reason": "이미 회수됐거나 회수 중인 물건이에요"}
        if self._category(item_id) is None:
            return {"ok": False, "code": "no_category", "reason": "사진 분석이 끝나지 않아 품목을 몰라요 — 분석이 끝난 뒤 다시 눌러 주세요"}
        if not self._flow_begin(item_id):
            return {"ok": False, "code": "busy", "reason": "이 물건은 지금 진행 중이에요"}
        self._spawn(self._collect_by_staff, item_id)
        return {"ok": True, "reason": ""}

    def _collect_by_staff(self, item_id: str) -> None:
        w = self.world
        sid = self.wait_story.pop(item_id, None) or self.board.new_story("found", f"직원 회수 · {item_id}")
        with self.board.bind(sid):
            try:
                self.board.set_ids(sid, item_id=item_id)
                for st in ("intake", "features"):
                    self.board.stage(st, "done")
                cat = self._category(item_id)
                slot = w.reserved_for(item_id) or w.reserve_slot(item_id, cat)
                with w._lock:
                    if item_id in w.wait_queue:
                        w.wait_queue.remove(item_id)
                self.rep.progress(item_id, "직원이 회수 시작", "통합 시연 화면의 [본센터로 회수]")
                if slot is not None:
                    self._collect_store(sid, item_id)
                    return
                # 맞는 빈 칸이 없음 → 직원 보관 선반(S-n). 반환은 직원이 건넨다
                self.board.stage("collect", "active", "맞는 빈 칸이 없어 직원 보관 선반으로 회수")
                w.db_set_status(item_id, "회수 중", changed_by="staff")
                w.move(item_id, LOC_TRANSIT)
                w.sleep(3.0)
                try:
                    self.svc.move_to_shelf({"item_id": item_id})
                except Exception:
                    w.to_shelf(item_id)
                w.db_set_status(item_id, "본센터 보관", changed_by="staff")
                self.board.stage("collect", "done")
                self.board.stage("stored", "done", "직원 보관 선반")
                self.rep.progress(item_id, "직원 보관 선반에 보관", "보관함 열이 꽉 차 선반에 둠 — 반환은 직원이 건넴")
                self.board.finish(sid, f"{item_id} 직원 보관 선반에 보관(보관함 열이 꽉 참) — 반환은 직원이 건넴", True)
            except Exception as e:
                self.rep.alert(item_id, f"직원 회수 진행 오류({type(e).__name__})", "")
                self.board.finish(sid, f"진행 오류({type(e).__name__})", False)
            finally:
                self._flow_end(item_id)

    def purge_item(self, item_id: str) -> dict:
        """[기록 삭제](로봇 작업대 화면): 물건 하나에 딸린 기록을 **전부** 지운다(되돌릴 수 없음) — 물건·상태 기록·연락처·보관 칸·
        찾기 요청(확인 질문·방문 예약 포함)·반환 기록. 가상 세계와 팀 DB(함께 저장 중이면) 모두. 사진 파일만 남는다.
        로봇이 들고 있거나 반환 중인 물건, 이야기가 진행 중인 물건은 지우지 않는다. → {"ok", "reason", "claims", "cases", "slot"}"""
        w = self.world
        row = w.items.get(item_id)
        if row is None:
            return {"ok": False, "code": "not_found", "reason": "없는 물건 번호예요"}
        if row.get("loc") == LOC_GRIPPER or row.get("status") == "반환 중" or w.arm.get("holding") == item_id:
            return {"ok": False, "code": "busy", "reason": "반환 중인 물건은 지울 수 없어요 — 반환이 끝난 뒤 다시 눌러 주세요"}
        with self._flow_lock:
            if item_id in self._flowing and item_id not in self.qwen_wait:
                return {"ok": False, "code": "busy", "reason": "이 물건은 지금 회수가 진행 중이에요 — 끝난 뒤 다시 눌러 주세요"}
        slot = w.slot_id_of(item_id)
        self.cancelled.add(item_id)
        try:                                            # 보관함 정답지의 칸 기록(선반 포함)부터 비운다
            self.svc.storage.release(item_id=item_id)
        except Exception:
            pass
        if w.purge_item(item_id) is None:
            self.cancelled.discard(item_id)
            return {"ok": False, "code": "busy", "reason": "반환 중인 물건은 지울 수 없어요 — 반환이 끝난 뒤 다시 눌러 주세요"}
        claims = cases = []
        try:
            claims = self.svc.claims.delete_for_item(item_id)
        except Exception:
            claims = []
        try:
            cases = self.svc.recorder.delete_for_item(item_id)
        except Exception:
            cases = []
        # 이 물건을 기다리던 것들: 사진 분석 대기 · 칸 대기 이야기 · 확인 질문 답 대기 · 방문 대기
        ev = self.qwen_wait.get(item_id)
        if ev is not None:
            ev.set()
        story = self.wait_story.pop(item_id, None)
        if story:
            self.board.finish(story, f"{item_id} 기록 삭제 — 직원이 지움", False)
        for pid in [p for p, v in list(self.pending.items()) if any((c or {}).get("item_id") == item_id for c in (v.get("cands") or []))]:
            self.pending.pop(pid, None)
        for cid in claims:
            sid = self.visit_wait.pop(cid, None)
            if sid:
                self.board.finish(sid, f"{item_id} 기록 삭제 — 찾기 요청 {cid} 도 함께 지움", False)
        self.rep.progress(item_id, "기록 삭제", f"직원이 물건 기록을 모두 지움(찾기 요청 {len(claims)}건 · 반환 기록 {len(cases)}건 포함, 사진 파일은 남음)")
        return {"ok": True, "reason": "", "claims": claims, "cases": cases, "slot": slot}

    def cancel_item(self, item_id: str) -> dict:
        """[접수 취소]: 실수로 찍어 접수한 물건을 기록에서 지운다(되돌릴 수 없음). 아직 등록기계에 있고 찾는 사람이 없을 때만.
        → {"ok", "reason"}. 사진 분석을 기다리던 이야기는 '접수 취소'로 끝난다. 사진 파일은 남는다"""
        w = self.world
        row = w.items.get(item_id)
        if row is None:
            return {"ok": False, "code": "not_found", "reason": "없는 물건 번호예요"}
        if row.get("status") != "등록기계 보관" or row.get("loc") != LOC_KIOSK:
            return {"ok": False, "code": "state", "reason": "이미 회수된 물건은 취소할 수 없어요 — 직원이 확인해 주세요"}
        try:
            claimed = self.svc.claims.active_for_item(item_id)
        except Exception:
            claimed = None
        if claimed:
            return {"ok": False, "code": "claimed", "reason": "찾기 요청이 걸린 물건은 취소할 수 없어요"}
        waiting_qwen = item_id in self.qwen_wait
        with self._flow_lock:
            if item_id in self._flowing and not waiting_qwen:
                return {"ok": False, "code": "busy", "reason": "이 물건은 지금 회수가 진행 중이에요"}
        self.cancelled.add(item_id)
        if w.delete_item(item_id) is None:              # 그 사이 회수가 시작됨
            self.cancelled.discard(item_id)
            return {"ok": False, "code": "state", "reason": "이미 회수된 물건은 취소할 수 없어요 — 직원이 확인해 주세요"}
        ev = self.qwen_wait.get(item_id)
        if ev is not None:
            ev.set()                                    # 사진 분석을 기다리던 이야기를 깨워 '접수 취소'로 끝낸다
        story = self.wait_story.pop(item_id, None)
        if story:
            self.board.finish(story, f"{item_id} 접수 취소 — 기록에서 지움", False)
        self.rep.progress(item_id, "접수 취소", "직원이 접수를 취소해 기록에서 지움(사진 파일은 남음)")
        return {"ok": True, "reason": ""}

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
        self._flow_begin(item_id)
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
                if item_id not in self.world.items:          # 기다리는 동안 접수 취소 또는 가상 세계 초기화
                    self.board.finish(sid, f"{item_id} 접수 취소 — 기록에서 지움" if item_id in self.cancelled else "가상 세계 초기화로 중단", False)
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
                self._talk_found(item_id, row)
                self._collect_store(sid, item_id)
            except Exception as e:
                self.rep.alert(item_id, f"키오스크 습득 진행 오류({type(e).__name__})", "")
                self.board.finish(sid, f"진행 오류({type(e).__name__})", False)
            finally:
                self._flow_end(item_id)

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
            if _far_color(desc.get("color"), f.get("color")):
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
        if FOUND_SAY.search(clean) and not LOST_SAY.search(clean):
            raise RequestError(TO_FOUND)
        if has_pii(clean):   # 11/8 웹 무작위 시험: 하이픈 없는 번호(01012345678)가 화면 검사를 지나 그대로 접수됐다
            raise RequestError("분실 신고에 전화번호·주민등록번호 같은 개인정보는 쓰지 마세요")
        desc = query_features(clean)
        if "category" not in desc:
            raise RequestError(f"무엇을 잃어버렸는지 알 수 없어요 — {active_category_text()} 중 하나를 넣어 주세요")
        if not is_active_category(desc["category"]):                # 11/9 운영하지 않는 품목(립밤)은 찾기 접수 안 함
            raise RequestError(inactive_category_message(desc["category"]))
        return self._next(desc, lost_station(clean), tags, set(), opts or {})

    def _next(self, desc: dict, station: str | None, tags: set[str], asked: set[str], opts: dict | None = None) -> dict:
        """후보 고르기 → (필요하면 질문) → 찾기 요청. 질문은 칸마다 한 번만 한다.
        11/4 무작위 시험: 색을 말하지 않으면 같은 점수 후보 중 번호순 첫 물건을 마음대로 골랐다 → 먼저 색을 물어 좁힌다"""
        cands = self.candidates(desc, station)
        if not cands:
            if (opts or {}).get("visit") == "kiosk" and (opts or {}).get("id_no_masked"):
                return self._wait_lost(desc, station, tags, opts)       # 본인 확인 정보를 받은 웹·챗봇 신고는 대기로 받아 둠
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

    # ----- 11/9 분실인 먼저 신고 → 대기 → 습득물이 들어오면 연결 -----
    def _wait_lost(self, desc: dict, station: str | None, tags: set[str], opts: dict) -> dict:
        with self._wait_lock:
            self._wait_no += 1
            wid = f"L-{date.today():%Y%m%d}-{self._wait_no:04d}"
        sid = self.board.new_story("lost", f"분실 신고 대기 · {_summary(desc)}")
        with self.board.bind(sid):
            self.board.stage("claim", "active", "닮은 습득물이 아직 없음 — 들어오면 찾기 요청으로 자동 연결")
            self.rep.progress(wid, "분실 신고 대기", f"{_summary(desc)}{' · ' + station + '역' if station else ''} · 습득물을 기다림")
        with self._wait_lock:
            self.waiting_lost[wid] = {"desc": dict(desc), "station": station, "tags": set(tags), "opts": dict(opts),
                                      "story_id": sid, "t": time.time(), "claim_id": None, "item_id": None}
        return {"waiting": True, "wait_id": wid, "story_id": sid, "candidates": [],
                "visit": "kiosk", "message": "닮은 습득물이 아직 없어 분실 신고를 대기로 받아 두었어요"}

    def _match_waiting(self, item_id: str) -> None:
        """새 습득물(특징 분석 끝)과 닮은 대기 분실 신고를 먼저 들어온 순서로 하나만 찾기 요청으로 잇는다.
        확인 질문은 대기 신고 때 말한 특징으로만 채점(말하지 않은 칸은 미통과 → 방문 때 직원 확인). 로봇·반환은 기존 흐름 그대로"""
        with self._wait_lock:
            waits = sorted(((k, v) for k, v in self.waiting_lost.items() if v["claim_id"] is None), key=lambda kv: kv[1]["t"])
        for wid, w in waits:
            cands = [c for c in self.candidates(w["desc"], w["station"]) if c["item_id"] == item_id]
            if not cands:
                continue
            with self._wait_lock:
                if w["claim_id"] is not None:
                    continue
                w["claim_id"] = "연결 중"
            try:
                res = self._claim(w["desc"], w["station"], cands, w["tags"], w["opts"])
            except Exception as e:
                with self._wait_lock:
                    w["claim_id"] = None
                self.rep.alert(wid, f"대기 분실 신고 연결 실패({type(e).__name__})", f"물건 {item_id}")
                continue
            with self._wait_lock:
                w["claim_id"], w["item_id"] = res["claim_id"], item_id
            with self.board.bind(w["story_id"]):
                self.board.stage("claim", "done", f"습득물 {item_id} 들어옴 → 찾기 번호 {res['claim_id']}")
                self.rep.progress(wid, "대기 분실 신고 연결", f"습득물 {item_id} → 찾기 번호 {res['claim_id']}")
                self.board.finish(w["story_id"], f"찾기 번호 {res['claim_id']} 로 이어짐(진행은 새 이야기 {res['story_id']})", True)
            return

    def wait_status(self, wid: str) -> dict:
        """대기 번호 상태: waiting(아직) | matched(찾기 번호 생김) | unknown"""
        with self._wait_lock:
            w = self.waiting_lost.get(wid)
            if w is None:
                return {"wait_id": wid, "state": "unknown"}
            if w["claim_id"] and w["claim_id"] != "연결 중":
                return {"wait_id": wid, "state": "matched", "claim_id": w["claim_id"], "item_id": w["item_id"], "story_id": w["story_id"]}
            return {"wait_id": wid, "state": "waiting", "story_id": w["story_id"]}

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
        wait_kiosk = opts.get("visit") == "kiosk" or getattr(self.svc, "taught_robot", False)
        self._spawn(self._after_lost, sid, cid, pick, tags, wait_kiosk)
        return {"story_id": sid, "claim_id": cid, "item_id": pick, "candidates": cands, "quiz_passed": passed,
                "visit": "kiosk" if wait_kiosk else "auto"}

    def _after_lost(self, sid: str, cid: str, item_id: str, tags: set[str], wait_kiosk: bool = False) -> None:
        w = self.world
        with self.board.bind(sid):
            try:
                self.board.stage("visit", "active", "물건이 보관함에 올 때까지 기다림")
                # 11/9: 칸 대기(보관함이 꽉 차 등록기계에 있는) 물건을 찾는 사람이 생기면 줄을 기다리지 않는다 —
                # 바로 본센터로 회수해 직원 보관 선반에 두고(로봇 칸이 필요 없음) 직원이 건넨다. 예전에는 120초 뒤 '보관함에 없음'으로 끝났다
                if item_id in w.wait_queue and w.items[item_id]["loc"] == LOC_KIOSK:
                    self._claimed_to_shelf(cid, item_id)
                end = time.time() + self.visit_wait_s
                # 11/9 직원 보관 선반 물건도 본센터에 있는 것(반환은 로봇 없이 직원이 건넴)
                while not (w.items[item_id]["status"] == "본센터 보관" and w.items[item_id]["loc"] in (LOC_BIN, LOC_SHELF)):
                    if time.time() > end:
                        self.rep.alert(cid, "물건이 보관함에 없음 — 반환 시작 안 함", f"물건 {item_id}")
                        self.board.finish(sid, "물건이 보관함에 없음", False)
                        return
                    time.sleep(0.3)
                if wait_kiosk:                 # 11/7 웹 신고: 본센터 키오스크 '물건 찾으러 왔어요'에서 찾기 번호 입력을 기다림
                    self.board.stage("visit", "active", "본센터 방문 대기 · 키오스크 회수 탭에서 찾기 번호 입력"
                                 + (" · 직원 보관 선반 물건 — 직원이 가져다 드려요" if w.items[item_id]["loc"] == LOC_SHELF else ""))
                    self.rep.progress(cid, "본센터 방문 대기", "분실인이 부산역 본센터 키오스크에서 찾기 번호·신분 번호를 입력하면 반환 시작")
                    self.visit_wait[cid] = sid
                    return
                shelf = w.items[item_id]["loc"] == LOC_SHELF
                self.board.stage("visit", "active", "분실인 도착 · 직원 확인 중" + (" · 직원 보관 선반 물건 — 직원이 가져다 드려요" if shelf else ""))
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
                    shelf_case = "선반" in str(out.get("reason"))
                    self.board.stage("handover", "todo", "직원이 선반에서 가져다 드려요 · 직원 화면에서 교차 검증" if shelf_case
                                     else "직원 화면에서 '분실인에게 건넴'")
                    self.board.finish(sid, (f"직원 보관 선반 물건 — 직원이 가져다 드려요 · /staff 에서 교차 검증({out['case_id']})" if shelf_case
                                            else f"제출보관함 전달 완료 — 직원 화면 /staff 에서 교차 검증({out['case_id']})"), True)
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
            self.board.stage("handover", "todo", "직원이 선반에서 가져다 드려요 · 교차 검증 대기(/staff)"
                             if "선반" in str(out.get("reason")) else "제출보관함 · 직원 교차 검증 대기(/staff)")
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
        if getattr(self.svc, "taught_robot", False):
            raise Conflict("real_robot", "실물 연결 모드에서는 가상 초기화를 사용할 수 없습니다")
        w = self.world
        if self.talk is not None:                        # 11/9 에이전트가 배운 점도 처음으로(시연을 처음부터 다시 보여 주려고)
            self.talk.reset()
        with self._wait_lock:                            # 11/9 대기 분실 신고도 처음으로
            self.waiting_lost.clear()
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
                w.collecting.clear()
                w.wait_queue.clear()
                w.arm.update(x=w.arm["x"], phase="대기", holding=None, stopped=False, target=None)
                w.faults.update(grasp_fail=0, calib_fail=False, blur=False)
                w.seed()
            finally:
                w.on_bin, w.reserved = hooks
        SimRobot(w).robot_home()
        self.pending.clear()
        self.visit_wait.clear()
        self.wait_story.clear()
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
    # 11/10 처음 보관함 물건: 기본 = 분홍 핸드크림 하나. TOWER_SIM_SEED=full 이면 예전 5개(휴대폰 2·보조배터리 2·카드지갑 1 — 칸 대기·닮은 물건 장면 연습용)
    seed = str(env.get("TOWER_SIM_SEED") or "").strip().lower()
    world = SimWorld(speed=num("TOWER_SIM_SPEED", 1.0), seed=seed if seed == "full" else True)
    board = LiveBoard()
    real_vision = vision_part_from_env(env)
    matcher = matcher_part_from_env(env)
    topview = real_vision or SimTopview(world)
    from agents import taught_return
    taught = taught_return.enabled(env)
    robot = taught_return.remote_part(env) if taught else SimRobot(world)

    def factory():
        return CompositeBackend(vision=topview, matcher=matcher, db=world, robot=robot, fallback=MockBackend())
    reviewer = None
    if flag("TOWER_REVIEWER"):
        from agents.llm_reviewer import OllamaReviewer
        reviewer = OllamaReviewer()
    svc = TowerService(factory, LiveReporter(Reporter(dry_run=not flag("TOWER_SEND")), board), reviewer=reviewer,
                       claims=SimClaimStore(world), intake=world, gpu_lease=lease_from_env(env))
    svc.board, svc.world = board, world
    taught_return.configure(svc, env)
    if taught:
        original_flow = svc.flow

        def taught_flow(req, backend, reporter, **kwargs):
            result = original_flow(req, backend, reporter, **kwargs)
            if result.decision == DECISION_RETURNED and not req.staff_shelf:
                from agents.sim_world import LOC_BASKET
                # Expected location after motion; staff verification still required.
                world.move(req.item_id, LOC_BASKET)
            return result
        svc.flow = taught_flow
    svc.sim = SimDirector(svc, world, board, auto_handover=not taught and not flag("TOWER_SIM_MANUAL_HANDOVER"),
                          qwen_wait_s=num("TOWER_SIM_QWEN_WAIT", 180))
    link_storage(svc, world)
    from agents.tower_brain import build_from_env     # 11/8 관제탑 메인 AI(.env TOWER_BRAIN=1 일 때만)
    svc.brain = build_from_env(slot_lookup=lambda item_id: sim_slot_area(svc, world, item_id))
    from agents.agent_talk import build_talk             # 11/9 에이전트 대화(가상 시연은 기본 켜짐, TOWER_AGENT_TALK=0 이면 끔)
    svc.talk = build_talk(svc.reporter, env, sim=True)
    svc.slot_lookup = lambda item_id: sim_slot_area(svc, world, item_id)
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
        with world._lock:                              # 칸 대기·회수 중이던 물건을 직원이 직접 넣음
            world.collecting.pop(item_id, None)
            if item_id in world.wait_queue:
                world.wait_queue.remove(item_id)
        return out
    st.place = place
    orig_release, orig_shelf = st.release, st.move_to_shelf

    def release(item_id=None, slot_id=None):
        """11/9 칸 비우기: 직원이 칸에서 물건을 꺼냄(가상 세계: 직원 손 → 보관 화면 도착 대기) → 칸 대기 물건 회수"""
        out = orig_release(item_id=item_id, slot_id=slot_id)
        got = out.get("item_id")
        sid = out.get("slot_id")
        row = world.items.get(got) if got else None
        if row is not None and sid and world.slot_id_of(got) == sid:
            world.move(got, LOC_STAFF)
        d = getattr(svc, "sim", None)
        if d is not None:
            d.kick_wait()
        return out
    st.release = release

    def move_to_shelf(item_id, by="staff"):
        """11/9 직원 보관 선반: 가상 세계도 선반으로(보관 칸이 비면 칸 대기 물건 회수)"""
        out = orig_shelf(item_id, by=by)
        world.to_shelf(item_id)
        d = getattr(svc, "sim", None)
        if d is not None:
            sid = d.wait_story.pop(item_id, None)       # 칸 대기 이야기 → 직원이 가져와 선반에 둠으로 끝냄
            if sid:
                d.board.stage("collect", "done", "직원이 등록기계에서 가져옴", story_id=sid)
                d.board.stage("stored", "done", f"직원 보관 선반 {out.get('slot_id')}", story_id=sid)
                d.board.finish(sid, f"{item_id} 직원 보관 선반에 보관 — 반환은 직원이 건넴", True)
            d.kick_wait()
        return out
    st.move_to_shelf = move_to_shelf
    for r in list(world.items.values()):              # 시작할 때 이미 칸에 있는 시연 물건
        sid = world.slot_id_of(r["item_id"])
        if sid:
            on_bin(r["item_id"], sid)


__all__ = ["SimDirector", "SimClaimStore", "build_sim_service"]
