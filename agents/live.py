"""진행 기록판(LiveBoard) — 실시간 화면(/live)과 분실물 봇이 읽는 관제탑 사건 목록 (LF-17·LF-29, 11/4).

한줄 설명: 관제탑이 디스코드 관제 채널로 보내는 모든 메시지(진행·경보·팀 요약)를 같은 순서로 여기에도 쌓아 두고,
화면·봇이 "N번 이후 새 사건"을 물으면 돌려준다. 사건마다 어느 이야기(습득 신고·분실 신고)의 어느 단계인지 붙인다.

- LiveReporter 는 기존 Reporter 를 감싸기만 한다 → 디스코드 전송·개인정보 검사 규칙은 그대로(막힌 메시지는 기록판에도 안 쌓임)
- 이야기 번호는 연출기(sim_director)가 실행하는 스레드에 묶는다(bind). 반환 흐름도 같은 스레드에서 돌아 자동으로 붙는다
- 표준 라이브러리만 쓴다. 메모리에만 둔다(최근 MAX_EVENTS 개)
"""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager

MAX_EVENTS = 600

# 이야기 단계(화면의 진행 막대 순서). 습득 신고 / 분실 신고
FOUND_STAGES = [("intake", "등록기계 접수"), ("features", "Qwen 특징 분석"), ("collect", "본센터로 회수"),
                ("stored", "보관함 배치")]
LOST_STAGES = [("claim", "찾기 요청·확인 질문"), ("approve", "메인 AI 승인"), ("visit", "방문·직원 확인"),
               ("topview", "탑뷰 촬영"), ("match", "매칭"), ("approach", "사전 접근"), ("grasp", "집기"),
               ("deliver", "제출보관함 전달"), ("handover", "인계 완료")]

# 반환 흐름(supervisor)·서비스가 보내는 단계 이름 → 이야기 단계
STEP_STAGE = {"메인 AI 승인 · 수령 예약": "approve", "직원 확인 완료": "visit", "탑뷰 촬영": "topview",
              "매칭 완료": "match", "GPU 사용권 받음": "approach", "사전 접근 완료": "approach", "집기 성공": "grasp",
              "집기 실패": "grasp", "제출보관함 전달 완료": "deliver", "바구니 전달 완료": "deliver", "인계 완료": "handover",
              "직원 보관 선반 · 로봇 없이 직원 인계": "deliver"}
# 11/9 직원 보관 선반 물건: 로봇 단계는 건너뜀(skip)으로 칠한다
SHELF_SKIP = ("topview", "match", "approach", "grasp")


# 경보 내용 → 실패로 칠할 단계(11/4 무작위 시험: '지금 진행 중인 단계'만 보면 확인 질문 미통과가 '방문'에 칠해졌다)
ALERT_STAGE = [("확인 질문", "approve"), ("동의", "approve"), ("본인인증", "approve"), ("메인 AI 검토", "approve"),
               ("승인 보류", "approve"), ("물건 기록 없음", "approve"), ("신분증", "visit"), ("안쪽 특징 불일치", "visit"),
               ("보관함에서 물건", "topview"), ("매칭", "match"), ("닮은 물건", "match"), ("작업대 좌표", "approach"),
               ("GPU", "approach"), ("사전 접근", "approach"), ("집기", "grasp"), ("바구니", "deliver"),
               ("인계", "handover")]


class LiveBoard:
    def __init__(self):
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._seq = 0
        self._local = threading.local()
        self.stories: dict[str, dict] = {}
        self._story_no = 0

    # ----- 이야기 -----
    def new_story(self, kind: str, title: str) -> str:
        with self._lock:
            self._story_no += 1
            sid = f"T{self._story_no:03d}"     # T = 이야기(서면 접수 번호 S-… 와 헷갈리지 않게)
            stages = FOUND_STAGES if kind == "found" else LOST_STAGES
            self.stories[sid] = {"story_id": sid, "kind": kind, "title": title, "result": None, "ids": {},
                                 "stages": [{"key": k, "label": l, "state": "todo", "detail": ""} for k, l in stages],
                                 "started": time.time()}
            return sid

    @contextmanager
    def bind(self, story_id: str | None):
        """이 스레드에서 나오는 사건에 이야기 번호를 붙인다."""
        prev = getattr(self._local, "story", None)
        self._local.story = story_id
        try:
            yield
        finally:
            self._local.story = prev

    def current(self) -> str | None:
        return getattr(self._local, "story", None)

    def stage(self, key: str, state: str = "done", detail: str = "", story_id: str | None = None) -> None:
        """이야기 단계 표시 바꾸기: todo | active | done | fail | skip"""
        sid = story_id or self.current()
        with self._lock:
            st = self.stories.get(sid or "")
            if not st:
                return
            for s in st["stages"]:
                if s["key"] == key:
                    s["state"], s["detail"] = state, detail or s["detail"]
            self._seq += 1
            self._events.append({"seq": self._seq, "t": time.time(), "story": sid, "channel": "stage",
                                 "title": key, "body": state, "stage": key})
            del self._events[:-MAX_EVENTS]

    def set_ids(self, story_id: str, **ids) -> None:
        with self._lock:
            if story_id in self.stories:
                self.stories[story_id]["ids"].update({k: v for k, v in ids.items() if v})

    def finish(self, story_id: str, result: str, ok: bool) -> None:
        with self._lock:
            st = self.stories.get(story_id)
            if st:
                st["result"] = {"text": result, "ok": ok, "t": time.time()}
                for s in st["stages"]:     # 11/4 화면 시험: 끝난 이야기에 '진행 중'(깜박임) 단계가 남아 있었다
                    if s["state"] == "active":
                        s["state"] = "done" if ok else "todo"
            self._seq += 1
            self._events.append({"seq": self._seq, "t": time.time(), "story": story_id, "channel": "result",
                                 "title": result, "body": "ok" if ok else "fail", "stage": None})

    def _active_stage(self, sid: str) -> str | None:
        st = self.stories.get(sid or "")
        if not st:
            return None
        act = [s["key"] for s in st["stages"] if s["state"] == "active"]
        if act:
            return act[-1]
        todo = [s["key"] for s in st["stages"] if s["state"] == "todo"]   # 경보가 난 곳 = 아직 안 끝난 첫 단계
        return todo[0] if todo else None

    # ----- 사건 -----
    def add(self, channel: str, title: str, body: str = "") -> dict:
        sid = self.current()
        step = title.split("] ", 1)[1] if title.startswith("[") and "] " in title else title
        stage = STEP_STAGE.get(step)
        with self._lock:
            self._seq += 1
            ev = {"seq": self._seq, "t": time.time(), "story": sid, "channel": channel, "title": title, "body": body,
                  "stage": stage}
            self._events.append(ev)
            del self._events[:-MAX_EVENTS]
            st = self.stories.get(sid or "")
        if st and stage:
            if step.startswith("직원 보관 선반"):
                for k in SHELF_SKIP:
                    self.stage(k, "skip", "직원 보관 선반 — 로봇 안 씀", sid)
                with self._lock:            # 11/9: 선반 물건은 '제출보관함 전달'이 아니라 직원이 선반에서 가져옴 — 단계 이름도 바꿈
                    st2 = self.stories.get(sid)
                    for s in (st2 or {}).get("stages", []):
                        if s["key"] == "deliver":
                            s["label"] = "직원이 선반에서 가져옴"
            self.stage(stage, "fail" if step == "집기 실패" else "done", body, sid)
        elif st and channel == "alert":
            key = next((k for word, k in ALERT_STAGE if word in title), None) or self._active_stage(sid)
            if key:
                self.stage(key, "fail", body, sid)
        return ev

    def agent_say(self, frm: str, to: str, kind: str, text: str, score: int | None = None, ref: str = "") -> dict:
        """11/9 에이전트 대화 한 마디(agents/agent_talk.py). 채널 'agent' 사건으로 쌓아 /live 에이전트 대화 패널이 읽는다"""
        sid = self.current()
        with self._lock:
            self._seq += 1
            ev = {"seq": self._seq, "t": time.time(), "story": sid, "channel": "agent", "title": f"{frm} → {to}",
                  "body": text, "stage": None, "agent": {"from": frm, "to": to, "kind": kind, "score": score, "ref": ref}}
            self._events.append(ev)
            del self._events[:-MAX_EVENTS]
        return ev

    def since(self, after: int = 0, story: str | None = None, limit: int = 200) -> list[dict]:
        with self._lock:
            evs = [e for e in self._events if e["seq"] > after and (story is None or e["story"] == story)]
        return evs[:limit]

    @property
    def last_seq(self) -> int:
        return self._seq

    def story(self, story_id: str) -> dict | None:
        with self._lock:
            st = self.stories.get(story_id)
            return None if st is None else {**st, "stages": [dict(s) for s in st["stages"]], "ids": dict(st["ids"])}

    def recent_stories(self, limit: int = 6) -> list[dict]:
        with self._lock:
            ids = list(self.stories)[-limit:]
        return [self.story(i) for i in reversed(ids)]


class LiveReporter:
    """기존 Reporter(디스코드 관제 채널)를 감싸 같은 메시지를 기록판에도 남긴다. Reporter 와 같은 함수를 가진다."""

    def __init__(self, inner, board: LiveBoard):
        self.inner = inner
        self.board = board

    @property
    def dry_run(self):
        return getattr(self.inner, "dry_run", True)

    @property
    def messages(self):
        return getattr(self.inner, "messages", [])

    @property
    def blocked(self):
        return getattr(self.inner, "blocked", [])

    def send(self, channel: str, title: str, body: str = "") -> bool:
        before = len(getattr(self.inner, "blocked", []))
        ok = self.inner.send(channel, title, body)
        if len(getattr(self.inner, "blocked", [])) == before:     # 개인정보로 막힌 메시지는 화면에도 안 띄움
            self.board.add(channel, title, body)
        return ok

    def progress(self, case: str, step: str, detail: str = "") -> bool:
        return self.send("progress", f"[{case}] {step}", detail)

    def alert(self, case: str, reason: str, detail: str = "") -> bool:
        return self.send("alert", f"[{case}] ⚠️ {reason}", detail)

    def score(self, title: str, body: str) -> bool:
        return self.send("score", title, body)

    def team(self, title: str, body: str = "") -> bool:
        return self.send("team", title, body)


__all__ = ["LiveBoard", "LiveReporter", "FOUND_STAGES", "LOST_STAGES", "STEP_STAGE"]
