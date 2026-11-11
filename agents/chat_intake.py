"""챗봇 대화 접수 에이전트 — 분실 접수·습득 신고를 대화로 (LF-5 · 11/9 변재원)

한줄 설명: "검정 지갑 잃어버렸어요"처럼 말하면 접수에 필요한 빈칸(품목·색·역·때·특징·본인 확인)을 하나씩 묻고,
요약을 보여 준 뒤 사용자가 [접수할게요]를 눌러야만 진짜 접수 창구(가상 시연 감독 SimDirector)를 부른다.

- 빈칸 채우기: 규칙(sim_world.query_features·역 이름)이 먼저, 그래도 비면 모델(Mi:dm, JSON 고를 값 목록)이 채우고 코드가 다시 검사
- 저장은 확인 버튼 뒤에만(사용자 확인 없이 접수하지 않음). 취소는 언제든 "취소"
- 본인 확인: 이름·주민번호 성별 숫자는 위젯이 화면에서 가린 값만 보낸다(intake_action). 질문 글로 받지 않는다
- 대화 상태는 관제탑 메모리에 session_id 별로 10분(관제탑을 끄면 사라짐). 개인정보 원문은 저장하지 않는다
- 창구(desk): 가상 시연 SimDirector(found·lost·answer). 없으면(실제 DB 모드) 키오스크·분실인 웹으로 안내
"""
from __future__ import annotations

import re
import secrets
import threading
import time

from agents.contracts import active_category_text, category_label, is_active_category, inactive_category_message

SESSION_TTL_S = 600
STATION_NAMES = ("서면", "해운대")                 # 등록기계가 있는 역(sim_world.STATIONS) — 주운 역은 이 둘만
LOST_STATION_NAMES = ("서면", "해운대", "부산")     # 11/10 잃어버린 역은 부산역(본센터)도(sim_world.LOST_STATIONS)
OTHER_STATION = re.compile(r"^(?:[가-힣A-Za-z0-9 ]{2,12}역|(?:열차|지하철|전철|전동차|객차|차)\s*(?:안|내|에서)?|(?:다른|딴)\s*역|역은?\s*아니)"
                           r"(?:\s*(?:이요|요|이에요|예요|입니다|에서요?|인\s*것\s*같아요|같아요))?[.!~]*$")   # "센텀시티역이요" · "열차 안에서요"
MASK_RE = re.compile(r"^[^\s*]{1,8}\*{0,8}[^\s*]?$")
ID_MASK_RE = re.compile(r"^\*{6}-[1-4]\*{6}$")

START_LOST = re.compile(r"분실\s*(?:접수|신고)|잃어버린\s*물건\s*(?:접수|신고|등록)|찾기\s*(?:접수|신청|요청)|접수\s*해\s*주|신고\s*해\s*주|"
                        r"(?:잃어버|잃었|분실)[^?!]{0,16}(?:접수|신고|등록)")   # 11/9 채점표: "…잃어버렸어요. 신고할게요"처럼 문장이 나뉘어도
START_FOUND = re.compile(r"습득\s*(?:신고|접수|등록)|주운\s*물건\s*(?:신고|접수|등록|맡기)|"
                         r"(?:주웠|주운|주워|습득)[^?!]{0,18}(?:신고|접수|등록|맡기|맡길|맡겨)")
HOW_ASK = re.compile(r"어디|어떻게|방법|절차|나요\s*\??\s*$|까요\s*\??\s*$|[?？]\s*$")
WANT = re.compile(r"싶|해\s*주|해\s*줄\s*(?:수|래)|할게|하려고|해줘|부탁|접수하기|신고하기|시작")
LOST_SAY = re.compile(r"잃어버|잃었|잊어버|분실|두고\s*내|놓고\s*내")
FOUND_SAY = re.compile(r"주웠|주운|주워|습득|발견했|떨어져\s*있|놓여\s*있")
CANCEL = re.compile(r"^(?:취소|그만|접수\s*취소|안\s*할래|처음부터|됐어요?|괜찮아요)\s*[.!]*$")
YES = re.compile(r"^(?:접수할게요|네|예|응|좋아요|맞아요|확인|접수|그래요?|ㅇㅇ|넵)\s*[.!]*$")
FIX = re.compile(r"^(?:고칠게요|수정|다시|고쳐|틀렸어요)\s*[.!]*$")
COLOR_HINT = re.compile(r"색|검|까만|까맣|블랙|흰|하얀|하양|화이트|회|그레이|갈|브라운|빨|레드|주황|오렌지|노랑|노란|초록|녹|파랑|파란|블루|남색|네이비|보라|분홍|핑크|베이지|은|실버|금|골드")
UNKNOWN_SAY = re.compile(r"^(?:모름|몰라요?|(?:잘\s*)?모르겠(?:어요?|음|네요?)|기억(?:이|은)?\s*(?:잘\s*)?안\s*(?:나요?|남|나네요?)|없어요|없음|건너뛰기|넘어가기)\s*[.!~ㅠㅜ]*$")
WHEN_RE = re.compile(r"(오늘|어제|그제|그저께|\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}/\d{1,2}|월요일|화요일|수요일|목요일|금요일|토요일|일요일)"
                     r"\s*(아침|오전|점심|오후|저녁|밤|새벽)?")
PLACE_DETAIL = re.compile(r"(\d+\s*번\s*출구[^.,]{0,10}|승강장[^.,]{0,8}|화장실|대합실|개찰구[^.,]{0,6}|계단[^.,]{0,6}|"
                          r"에스컬레이터|엘리베이터|지하상가|매표소|벤치|열차\s*안|\d+\s*호선[^.,]{0,6})")
MARK_RE = re.compile(r"([가-힣A-Za-z0-9]{1,8}\s*(?:스티커|키링|무늬|로고|글자|그림))")

LOST_ORDER = ("category", "color", "station", "when", "detail", "identity")
FOUND_ORDER = ("category", "color", "station", "place")
# 11/10 사람 조작 시뮬레이션: 핸드크림을 고른 뒤 색 선택지가 '검정·흰색·갈색·파랑'뿐이라 분홍·초록 핸드크림을 고를 수 없었다
# → 품목을 알면 그 품목의 실제 물건 색(구매 목록·시연 물건 기준)을 먼저 보여 준다. 다른 색은 글로 말하면 된다
COLOR_BY_CATEGORY = {"모형폰": ["검정", "흰색", "파랑"], "보조배터리": ["흰색", "검정"], "핸드크림": ["분홍", "초록", "흰색"],
                     "지갑": ["검정", "갈색"]}
CANCEL_ORDER = ("claim_id", "identity")      # 11/10 대화로 찾기 요청 취소: 찾기 번호 → 본인 확인(가린 값) → 확인 → 창구
CLAIM_RE = re.compile(r"\bC-\d{8}-\d{4}\b", re.I)
CANCEL_TARGET = re.compile(r"찾기\s*(?:요청|신청|번호)|방문\s*예약|수령\s*예약|예약|분실\s*(?:접수|신고)|C-\d{8}-\d{4}", re.I)
CANCEL_NO = re.compile(r"^(?:아니(?:요|오)?|아뇨|안\s*할래요?|그만(?:둘게요|둘래요|할게요)?|취소\s*안\s*해요?)\s*[.!]*$")
SLOT_KO = {"category": "물건", "color": "색", "station": "역", "when": "잃어버린 때", "detail": "특징(글자·스티커)",
           "identity": "본인 확인", "place": "주운 곳", "claim_id": "찾기 번호"}
QUESTIONS = {
    "category": f"어떤 물건인가요? ({active_category_text()} 중 하나)",
    "color": "물건 색이 무엇인가요? 가장 넓게 보이는 색 하나만 알려 주세요.",
    "station_lost": "어느 역에서 잃어버리셨나요? (서면·해운대·부산역 — 다른 역이거나 기억나지 않으면 '모름')",
    "station_found": "어느 역에서 주우셨나요? 등록기계가 있는 역은 서면·해운대예요.",
    "when": "언제쯤 잃어버리셨나요? 예: 어제 저녁 / 오늘 아침 (모르면 '모름')",
    "detail": "물건에 적힌 글자나 붙은 스티커가 있나요? 예: 별 스티커 (없으면 '없어요')",
    "identity": "마지막으로 본인 확인 정보가 필요해요. 아래 칸에 이름과 주민등록번호 뒷자리 첫 숫자를 넣어 주세요. "
                "화면에서 가려서(예: 홍*동, ******-1******) 보내고, 원래 값은 저장하지 않아요.",
    "place": "역 안 어디쯤에서 주우셨나요? 예: 5번 출구 앞 / 승강장 (모르면 '모름')",
    "claim_id": "취소할 찾기 번호를 알려 주세요. 접수할 때 받은 번호예요(예: C-20261110-0001).",
    "identity_cancel": "본인 확인이 필요해요. 아래 칸에 찾기 요청을 할 때 넣은 것과 같은 이름과 주민등록번호 뒷자리 첫 숫자를 넣어 주세요. "
                       "화면에서 가려서 보내고, 원래 값은 저장하지 않아요.",
}
CHOICES = {
    "category": ["휴대폰", "보조배터리", "핸드크림", "카드지갑"],     # 11/10: 보관함 열 순서, 지갑은 카드지갑으로 보여 줌
    "station_lost": ["서면", "해운대", "부산역", "모름"], "station_found": ["서면", "해운대"],     # 11/10 잃어버린 역은 모를 수 있다(주운 역은 등록기계라 꼭 필요)
    "color": ["검정", "흰색", "갈색", "파랑"],                  # 품목을 모를 때. 품목을 알면 아래 COLOR_BY_CATEGORY
    "when": ["오늘", "어제", "모름"], "detail": ["없어요"], "place": ["모름"],
}


class IntakeSessions:
    """session_id → 접수 대화 상태(관제탑 메모리, 10분). 여러 사람이 동시에 써도 섞이지 않게 잠금"""

    def __init__(self, ttl: float = SESSION_TTL_S, clock=time.time):
        self._d: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.ttl, self.clock = ttl, clock

    def get(self, sid: str | None) -> dict | None:
        if not sid:
            return None
        with self._lock:
            s = self._d.get(sid)
            if s and self.clock() - s["t"] > self.ttl:
                self._d.pop(sid, None)
                return None
            return s

    def put(self, sid: str, s: dict) -> None:
        with self._lock:
            s["t"] = self.clock()
            self._d[sid] = s
            for k in [k for k, v in self._d.items() if self.clock() - v["t"] > self.ttl]:
                self._d.pop(k, None)

    def drop(self, sid: str | None) -> None:
        with self._lock:
            self._d.pop(sid or "", None)

    def lock(self, sid: str | None):
        """대화 하나의 걸음을 한 번에 하나씩(11/9 정연우 검토: [접수할게요] 연속 클릭 → 중복 접수 막기)"""
        with self._lock:
            locks = self.__dict__.setdefault("_locks", {})
            return locks.setdefault(sid or "", threading.Lock())


WAIT_RE = re.compile(r"\bL-\d{8}-\d{4}\b")
# 11/9 채점표: "우산 분실 신고하고 싶어요"가 접수를 시작해 물건 종류를 다시 물었다 → 운영 4종 밖 물건 이름이면 바로 역무실 안내
OTHER_ITEM = re.compile(r"우산|가방|백팩|배낭|이어폰|에어팟|노트북|태블릿|아이패드|안경|선글라스|교통카드|옷|외투|패딩|모자|목도리|장갑|책|서류|열쇠|키\s|시계|반지|목걸이|인형|텀블러")


def detect_start(question: str) -> str | None:
    """접수를 시작하려는 말인지: "lost" | "found" | None. 단순 분실 이야기("지갑 잃어버렸어요")는 검색·안내 길이고,
    접수·신고·맡기기 말이 같이 있을 때만 접수 길로 간다(supervisor 가 검색 뒤 '접수할까요?'를 따로 제안)"""
    q = re.sub(r"\s+", " ", question or "")
    if WAIT_RE.search(q):
        return "status"                       # 11/9 분실 신고 대기 번호 조회
    if re.search(r"취소|철회", q):
        # 11/10 "찾기 요청 취소하고 싶어요"가 분실 접수 시작으로 읽혔다 → 취소는 분실 접수로 가지 않는다.
        # 찾기 번호가 있거나 '취소해 주세요·하고 싶어요'처럼 하려는 말이면 대화로 취소(본인 확인 뒤), 방법만 물으면 안내 길
        if CLAIM_RE.search(q) or (CANCEL_TARGET.search(q) and WANT.search(q) and not (HOW_ASK.search(q) and not WANT.search(q))):
            if not re.search(r"방법|어떻게|절차", q):
                return "cancel"
        return None
    # "주운 물건은 어디에 맡기나요?"처럼 방법을 묻는 말은 안내로(supervisor 가 '습득 신고하기' 버튼을 제안) — 하고 싶다는 말이 있을 때만 바로 시작
    if HOW_ASK.search(q) and not WANT.search(q):
        return None
    if START_FOUND.search(q):
        return "found"
    if START_LOST.search(q) and not FOUND_SAY.search(q):
        return "lost"
    if re.fullmatch(r"\s*(?:분실\s*접수(?:\s*시작)?|분실\s*접수하기)\s*", q):
        return "lost"
    if re.fullmatch(r"\s*(?:습득\s*신고(?:\s*시작)?|습득\s*신고하기)\s*", q):
        return "found"
    return None


def extract(text: str, kind: str, want: str | None = None) -> dict:
    """말에서 빈칸 값 뽑기(규칙). want = 지금 묻고 있는 칸(짧은 답 "서면이요"·"어제"를 그 칸으로 읽는다)"""
    from agents.sim_world import query_features
    t = text or ""
    out: dict = {}
    f = query_features(t)
    if f.get("category"):
        out["category"] = f["category"]
    if f.get("color"):
        out["color"] = f["color"]
    if kind == "lost":
        from agents.sim_world import lost_station
        st = lost_station(t)                      # 서면 · 해운대 · 부산(부산역·본센터)
    else:
        st = next((s for s in STATION_NAMES if s in t), None)
    if st:
        out["station"] = st
    m = WHEN_RE.search(t)
    if m:
        out["when"] = re.sub(r"\s+", " ", m.group(0)).strip()
    if kind == "lost":
        mk = MARK_RE.search(t)
        if mk:
            out["detail"] = re.sub(r"\s+", " ", mk.group(1)).strip()
        elif f.get("visible_text"):
            out["detail"] = f"글자 {f['visible_text']}"
    if kind == "found":
        pm = PLACE_DETAIL.search(t)
        if pm:
            out["place"] = re.sub(r"\s+", " ", pm.group(1)).strip()
    if want and UNKNOWN_SAY.match(t.strip()):
        out[want] = "없음" if want == "detail" and re.match(r"^(?:없어요|없음)", t.strip()) else "모름"
    elif want == "station" and kind == "lost" and not out and OTHER_STATION.match(t.strip()):
        # 11/10 목록에 없는 역("센텀시티역이요")을 말하면 같은 질문을 되풀이했다 → 그 역은 장소 확인에 쓸 수 없으니 '모름'과 같게 받고 다음으로
        out["station"] = "모름"
    elif want in ("detail", "place") and not out and len(t.strip()) <= 30 and not LOST_SAY.search(t):
        # 11/9 채점표: "아 오늘 아침이었어요"(때 고치기)가 특징 칸에도 통째로 들어갔다 → 이 말에서 다른 칸을 읽었으면 자유 답으로 쓰지 않음
        out[want] = t.strip().rstrip(".!요").strip() or "모름"
    return out


class IntakeAgent:
    """접수 대화 한 걸음. step() 결과는 챗봇 응답 모양({status, answer, choices, form?, intake})"""

    def __init__(self, desk=None, brain=None, sessions: IntakeSessions | None = None):
        self.desk = desk              # 가상 시연 SimDirector(found/lost/answer) 또는 None
        self.brain = brain            # chat_agents.AgentBrain(빈칸 채우기 모델) 또는 None
        self.sessions = sessions or IntakeSessions()

    def active(self, sid: str | None) -> dict | None:
        """진행 중인 접수 대화(완료 결과 기억은 제외)"""
        s = self.sessions.get(sid)
        return s if s and s.get("stage") != "done" else None

    def confirmation(self, sid, version=None):
        """화면에만 전달할 확인 값. 그래프·모델·trace에는 넣지 않는다."""
        s = self.sessions.get(sid)
        if not s or s.get('stage') not in ('confirm', 'done') or not s.get('confirmation_token'):
            return None
        if version is not None and version != s.get('version', 0):
            return None
        return {'type': 'confirm', 'draft_version': s.get('version', 0),
                'confirmation_token': s['confirmation_token']}

    @staticmethod
    def _confirmed(s, action):
        return bool(action and action.get('type') == 'confirm'
                    and action.get('draft_version') == s.get('version', 0)
                    and s.get('confirmation_token')
                    and secrets.compare_digest(action['confirmation_token'], s['confirmation_token']))

    def wants(self, sid: str | None, question: str) -> bool:
        """이번 말을 접수 일꾼이 받아야 하나: 진행 중이거나, 방금 끝난 접수에 확인을 또 누름(같은 결과를 돌려주려고)"""
        s = self.sessions.get(sid)
        if not s:
            return False
        return s.get("stage") != "done" or bool(YES.match((question or "").strip()))

    # ---------- 한 걸음 ----------
    def step(self, sid: str | None, question: str, start: str | None = None, action: dict | None = None,
             prior: list | None = None) -> dict:
        """prior: 앞 대화의 사용자 말(최근 몇 개). 접수를 새로 시작할 때 이미 말한 품목·색·역을 다시 묻지 않게 미리 채운다.
        같은 대화의 걸음은 한 번에 하나씩(잠금) — 확인 버튼을 두 번 눌러도 접수는 한 번"""
        lk = self.sessions.lock(sid)
        if not lk.acquire(timeout=60):
            return self._out("intake_failed", "앞 요청을 처리하는 중이에요. 잠시 뒤 다시 눌러 주세요.", None, done=True)
        try:
            return self._step(sid, question, start, check_action(action), prior)
        finally:
            lk.release()

    def _step(self, sid, question, start=None, action=None, prior=None) -> dict:
        s = self.sessions.get(sid)
        if action and action['type'] == 'confirm' and (not s or s.get('stage') not in ('confirm', 'done')):
            return self._out('intake_failed', '확인 요청이 만료되었거나 내용이 바뀌었어요. 현재 내용을 다시 확인해 주세요.', None)
        if s is not None and s.get("stage") == "done":
            if self._confirmed(s, action):
                last = dict(s["last"])
                last["answer"] = "이미 접수했어요. " + last["answer"]
                return last
            if YES.match((question or '').strip()) or action:
                return self._out('intake_failed', '유효한 확인 요청이 아니에요. 접수 결과를 확인해 주세요.', None)
            self.sessions.drop(sid)
            s = None
        if s is None and (start == "status" or (start is None and detect_start(question) == "status")):
            return self._status(question)
        if s is None:
            kind = start or detect_start(question)
            if kind is None:
                return self._out("intake_none", "", None, progress=False)
            m = OTHER_ITEM.search(question or "")
            if m and kind in ("lost", "found") and not extract(question, kind).get("category"):
                where = "역무실에 맡겨 주세요" if kind == "found" else "역무실에 문의해 주세요"
                return self._out("intake_failed", f"{m.group(0).strip()}은(는) 지금 운영하지 않는 물건이에요 — 지갑·휴대폰·핸드크림·보조배터리 "
                                                  f"4가지만 접수해요. {where}.", None, done=True)
            s = {"kind": kind, "slots": {}, "stage": "collect", "asked": None, "pending_id": None, "log": [], "fresh": True,
                 "version": 0}
            for said in [p for p in (prior or []) if isinstance(p, str) and kind in ("lost", "found")][-3:]:
                if (kind == "lost" and FOUND_SAY.search(said)) or (kind == "found" and LOST_SAY.search(said)):
                    continue                     # 반대 이야기(주운 이야기 → 분실 접수)는 가져오지 않음
                for k, v in extract(said, kind).items():
                    if k in ("category", "color", "station", "when") and k not in s["slots"]:
                        s["slots"][k] = v
                        s["log"].append({"slot": k, "by": "earlier_message"})
        q = (question or "").strip()
        if CANCEL.match(q) or (s["kind"] == "cancel" and CANCEL_NO.match(q)):
            self.sessions.drop(sid)
            if s["kind"] == "cancel":
                return self._out("intake_cancelled", "찾기 요청 취소를 그만뒀어요. 찾기 요청과 방문 예약은 그대로예요.", s, done=True)
            return self._out("intake_cancelled", "접수를 취소했어요. 다른 궁금한 점이 있으면 물어보세요.", s, done=True)
        if not sid:
            return self._out("intake_failed", "대화 번호가 없어 접수를 이어 갈 수 없어요. 챗봇 창에서 다시 시작해 주세요.", s, done=True)
        if s["stage"] == "quiz":
            return self._quiz_answer(sid, s, q)
        if s["stage"] == "confirm":
            if YES.match(q):
                if not self._confirmed(s, action):
                    return self._confirm(sid, s, note="확인 요청이 없거나 이전 내용의 요청이에요. 현재 요약의 확인 버튼을 눌러 주세요.")
                return self._commit(sid, s)
            if FIX.match(q):
                s["stage"], s["slots"], s["asked"] = "collect", {k: v for k, v in s["slots"].items() if k == "category"}, None
                self.sessions.put(sid, s)
                return self._ask_next(sid, s, note="처음 물건 종류만 남기고 다시 물어볼게요.")
        if not action and not s.get("fresh") and ((s["kind"] == "found" and LOST_SAY.search(q) and not FOUND_SAY.search(q))
                                                   or (s["kind"] == "lost" and FOUND_SAY.search(q) and not LOST_SAY.search(q))):
            # 11/9 채점표: 습득 신고 중 "저도 휴대폰 잃어버렸어요"가 주운 물건 종류를 휴대폰으로 바꿨다 → 다른 종류 이야기는 값으로 쓰지 않음
            other = "분실 접수" if s["kind"] == "found" else "습득 신고"
            self.sessions.put(sid, s)
            out = self._ask_next(sid, s, progress=False)
            out["answer"] = (f"지금은 {'습득 신고' if s['kind'] == 'found' else '분실 접수'} 중이에요. 이걸 먼저 끝내거나 '취소'한 뒤 "
                             f"{other}를 따로 시작해 주세요. ") + out["answer"]
            return out
        before = dict(s["slots"])
        self._fill(s, q, action)
        progressed = s["slots"] != before
        if progressed:            # 11/9 초안 번호: 값이 바뀌면 올라가고, 확인은 그 번호의 초안에만 유효
            s["version"] = s.get("version", 0) + 1
        if s["stage"] == "confirm" and not progressed and not YES.match(q):
            self.sessions.put(sid, s)
            return self._confirm(sid, s, note="접수하려면 [접수할게요], 고치려면 [고칠게요]를 눌러 주세요.", progress=False)
        if s["kind"] == "found" and s["slots"].get("category") and not is_active_category(s["slots"]["category"]):
            self.sessions.drop(sid)
            return self._out("intake_failed", inactive_category_message(s["slots"]["category"]) + " — 역무실에 맡겨 주세요.", s, done=True)
        if s["kind"] == "lost" and s["slots"].get("category") and not is_active_category(s["slots"]["category"]):
            self.sessions.drop(sid)
            return self._out("intake_failed", inactive_category_message(s["slots"]["category"]) + " — 역무실에 문의해 주세요.", s, done=True)
        return self._ask_next(sid, s, progress=progressed)

    # ---------- 빈칸 채우기 ----------
    def _fill(self, s: dict, q: str, action: dict | None) -> None:
        if action and action.get("type") == "identity":
            s["slots"]["identity"] = {"name_masked": action["name_masked"], "id_no_masked": action["id_no_masked"]}
            s["log"].append({"slot": "identity", "by": "form"})
            return
        if s["kind"] == "cancel":                    # 11/10 대화로 취소: 찾기 번호만 글에서 읽는다(모델 안 씀)
            m = CLAIM_RE.search(q)
            if m and s["slots"].get("claim_id") != m.group(0).upper():
                s["slots"]["claim_id"] = m.group(0).upper()
                s["log"].append({"slot": "claim_id", "by": "rule"})
            return
        rule = extract(q, s["kind"], s.get("asked"))
        # 사용자가 직접 말한 값(규칙으로 읽은 것)은 이미 채운 칸도 고친다("해운대였던 것 같아요" → 역 바로잡기)
        for k, v in rule.items():
            if k in self._order(s) and k != "identity" and s["slots"].get(k) != v:
                if k in s["slots"] and k != s.get("asked") and v == "모름":
                    continue                      # 다른 칸을 묻는 중의 '모름'으로 이미 채운 값을 지우지 않음
                s["slots"][k] = v
                s["log"].append({"slot": k, "by": "rule"})
        # 11/9 실제 Mi:dm 시험: "분실 접수하기"(내용 없는 말)에 모델이 역을 '서면'으로 지어냄 → 모델은 내용 있는 말에서
        # 품목·색만, 그 칸을 묻는 중(또는 첫 말)일 때만, 빈 칸에만 채운다(역은 이름이 둘뿐이라 규칙으로만)
        missing = [k for k in ("category", "color") if k not in s["slots"]]
        if (self.brain is not None and missing and s.get("asked") in (None, "category", "color") and len(q) >= 6 and not detect_start(q)
                and not YES.match(q) and not CANCEL.match(q)):
            for k, v in self._model_fill(q, s["kind"], missing).items():
                if k == "color" and not COLOR_HINT.search(q):
                    continue                          # 색 낱말이 없는데 색을 고르면 지어낸 것 → 버림
                if k not in s["slots"]:
                    s["slots"][k] = v
                    s["log"].append({"slot": k, "by": "model"})

    def _model_fill(self, q: str, kind: str, missing: list[str]) -> dict:
        """규칙이 못 읽은 빈칸을 모델이 고를 값 목록 안에서만 채운다(코드가 다시 검사). 모델이 없거나 틀리면 빈 dict"""
        from agents.contracts import ACTIVE_CATEGORIES
        colors = ["검정", "흰색", "회색", "갈색", "빨강", "주황", "노랑", "초록", "파랑", "남색", "보라", "분홍", "베이지", "은색", "금색"]
        props = {}
        if "category" in missing:
            props["category"] = {"type": "string", "enum": list(ACTIVE_CATEGORIES) + ["모름"]}
        if "color" in missing:
            props["color"] = {"type": "string", "enum": colors + ["모름"]}
        if "station" in missing:
            props["station"] = {"type": "string", "enum": list(STATION_NAMES) + ["모름"]}
        if not props:
            return {}
        schema = {"type": "object", "additionalProperties": False, "properties": props, "required": list(props)}
        try:
            parsed = self.brain.extract_slots(q, kind, schema)
        except Exception:
            return {}
        out = {}
        for k, v in (parsed or {}).items():
            if k in props and isinstance(v, str) and v in props[k]["enum"] and v != "모름":
                out[k] = v
        return out

    @staticmethod
    def _order(s: dict) -> tuple:
        return {"lost": LOST_ORDER, "cancel": CANCEL_ORDER}.get(s["kind"], FOUND_ORDER)

    # ---------- 다음 질문·확인 ----------
    def _ask_next(self, sid: str, s: dict, note: str = "", progress: bool = True) -> dict:
        missing = [k for k in self._order(s) if k not in s["slots"]]
        if not missing:
            s["stage"], s["asked"] = "confirm", None
            self.sessions.put(sid, s)
            return self._confirm(sid, s, note=note, progress=progress)
        k = missing[0]
        s["asked"] = k
        self.sessions.put(sid, s)
        key = f"station_{s['kind']}" if k == "station" else ("identity_cancel" if k == "identity" and s["kind"] == "cancel" else k)
        head = ({"lost": "분실 접수를 도와드릴게요. ", "cancel": "찾기 요청 취소를 도와드릴게요. "}.get(s["kind"], "습득 신고를 도와드릴게요. ")
                if s.pop("fresh", False) else "")
        filled = self._filled_text(s)
        answer = (note + " " if note else "") + head + (f"지금까지: {filled}. " if filled else "") + QUESTIONS[key]
        picks = COLOR_BY_CATEGORY.get(s["slots"].get("category"), CHOICES["color"]) if key == "color" else CHOICES.get(key, [])
        out = self._out("intake_question", answer.strip(), s, progress=progress, choices=list(picks) + ["취소"])
        if k == "identity":
            out["form"] = {"kind": "identity"}
            out["choices"] = ["취소"]
        return out

    def _confirm(self, sid: str, s: dict, note: str = "", progress: bool = True) -> dict:
        if s.get('confirm_version') != s.get('version', 0) or not s.get('confirmation_token'):
            s['confirmation_token'] = secrets.token_urlsafe(32)
        s["confirm_version"] = s.get("version", 0)
        self.sessions.put(sid, s)
        if s["kind"] == "cancel":
            answer = ((note + " " if note else "") + f"찾기 요청({s['slots']['claim_id']})을 취소할까요? 취소하면 방문 예약이 없어지고, "
                      "물건은 본센터에 계속 보관돼요(다시 찾기 요청할 수 있어요). 이미 방문해 반환이 시작된 요청은 취소할 수 없어요.")
            return self._out("intake_confirm", answer.strip(), s, progress=progress, choices=["네", "아니요"])
        what = "분실 접수" if s["kind"] == "lost" else "습득 신고"
        tail = (" 접수하면 찾기 번호가 나오고, 부산역 본센터 키오스크에서 찾기 번호와 신분증으로 받을 수 있어요."
                if s["kind"] == "lost" else " 접수하면 접수 번호가 나와요. 물건은 그 역 키오스크(습득물 등록기계) 상자에 넣어 주세요.")
        answer = (note + " " if note else "") + f"{what} 내용을 확인해 주세요: {self._filled_text(s)}." + tail
        return self._out("intake_confirm", answer.strip(), s, progress=progress, choices=["접수할게요", "고칠게요", "취소"])

    def _filled_text(self, s: dict) -> str:
        parts = []
        for k in self._order(s):
            v = s["slots"].get(k)
            if v is None:
                continue
            if k == "identity":
                parts.append(f"본인 확인 {v['name_masked']} · {v['id_no_masked']}")
            elif k == "category":
                parts.append(f"물건 {category_label(v)}")
            else:
                parts.append(f"{SLOT_KO[k]} {v}")
        return " · ".join(parts)

    def _finish(self, sid: str, s: dict, out: dict) -> dict:
        """세션 TTL 동안 결과를 기억(같은 유효 확인의 재전송은 다시 저장하지 않음)"""
        self.sessions.put(sid, {"kind": s["kind"], "stage": "done", "last": out, "slots": {}, "log": [],
                               'version': s.get('version', 0), 'confirmation_token': s.get('confirmation_token')})
        return out

    def _status(self, question: str) -> dict:
        wid = WAIT_RE.search(question or "").group(0)
        st = self.desk.wait_status(wid) if self.desk is not None and hasattr(self.desk, "wait_status") else {"state": "unknown"}
        info = {"kind": "status", "stage": "done", "wait_id": wid, "state": st.get("state")}
        if st.get("state") == "matched":
            ans = (f"대기 번호 {wid} 는 닮은 습득물({st.get('item_id')})이 들어와 찾기 번호 {st['claim_id']} 로 이어졌어요. "
                   "부산역 본센터 키오스크 '물건 찾으러 왔어요'에서 찾기 번호와 신분증 번호 뒤 첫 자리(신고할 때 고른 숫자)를 넣어 주세요.")
            info["claim_id"] = st["claim_id"]
        elif st.get("state") == "waiting":
            ans = f"대기 번호 {wid} 는 아직 닮은 습득물이 들어오지 않았어요. 들어오면 자동으로 찾기 번호가 만들어져요."
        else:
            ans = f"대기 번호 {wid} 를 찾지 못했어요(관제탑을 다시 켜면 지워져요). 번호를 확인해 주세요."
        return {"status": "intake_status", "answer": ans, "sources": [], "candidates": [], "choices": [],
                "item_search_performed": False, "generation_used": False, "generation_status": "intake",
                "method": "conversational_intake", "scope": "대화 접수", "intake": info}

    # ---------- 진짜 접수 ----------
    def _commit(self, sid: str, s: dict) -> dict:
        if s["kind"] == "cancel":
            return self._commit_cancel(sid, s)
        if self.desk is None:
            self.sessions.drop(sid)
            where = ("분실인 웹의 '잃어버린 물건 찾기' 또는 역 키오스크 '물건 잃어버렸어요'" if s["kind"] == "lost"
                     else "가까운 역 키오스크 '물건 주웠어요'")
            return self._out("intake_unavailable", f"지금 관제탑은 챗봇 접수 창구가 연결되지 않은 모드예요. 정리한 내용으로 {where}에서 접수해 주세요: "
                             f"{self._filled_text(s)}.", s, done=True)
        sl = s["slots"]
        try:
            if s["kind"] == "found":
                place = sl.get("place") if sl.get("place") not in (None, "모름") else ""
                color = "" if sl.get("color") in (None, "모름") else sl["color"] + " "
                text = f"{sl['station']}역 {place}에서 {color}{category_label(sl['category'])} 주웠어요".replace("  ", " ")
                rec = self.desk.found(text)
                return self._finish(sid, s, self._out("intake_done", f"습득 신고를 접수했어요. 접수 번호 {rec['item_id']} · {rec.get('place_text') or sl['station']}. "
                                 f"물건은 {sl['station']}역 키오스크 상자에 넣어 주세요. 사진 분석 → 본센터 회수까지는 관제탑이 이어서 처리해요.",
                                 s, done=True, ids={"item_id": rec["item_id"], "story_id": rec.get("story_id")}))
            text = self._lost_text(sl)
            ident = sl["identity"]
            opts = {"visit": "kiosk", "name_masked": ident["name_masked"], "id_no_masked": ident["id_no_masked"]}
            if sl.get("station") == "모름":
                opts["place_unknown"] = True      # 창구가 장소를 다시 묻지 않고, 확인 질문에서도 뺀다(색으로 확인)
            res = self.desk.lost(text, opts)
            return self._lost_result(sid, s, res)
        except Exception as e:                 # 창구가 거절한 이유(한국어 문장)는 그대로 보여 준다
            self.sessions.drop(sid)
            msg = str(e) if type(e).__name__ in ("RequestError", "NotFound") else f"접수 창구 오류({type(e).__name__})"
            return self._out("intake_failed", f"접수하지 못했어요: {msg}", s, done=True)

    def _commit_cancel(self, sid: str, s: dict) -> dict:
        """11/10 대화로 찾기 요청 취소 — 진짜 입구(SimDirector.cancel_claim → service.cancel_claim)를 그대로 쓴다.
        본인 확인(가린 신분 번호가 찾기 요청과 같아야 함)·방문 전만·틀린 횟수 잠금은 그 입구가 검사한다"""
        cancel = getattr(self.desk, "cancel_claim", None) if self.desk is not None else None
        if not callable(cancel):
            self.sessions.drop(sid)
            return self._out("intake_unavailable", "지금 관제탑은 챗봇 취소 창구가 연결되지 않은 모드예요. 분실인 웹의 진행 상황 화면에서 "
                             "[찾기 요청 취소]를 누르거나, 본센터 직원에게 찾기 번호를 말씀해 주세요.", s, done=True)
        sl = s["slots"]
        try:
            out = cancel(sl["claim_id"], id_no_masked=sl["identity"]["id_no_masked"])
        except Exception as e:
            self.sessions.drop(sid)
            name = type(e).__name__
            msg = str(e) if name in ("RequestError", "NotFound", "Conflict") else f"취소 창구 오류({name})"
            return self._out("intake_failed", f"취소하지 못했어요: {msg}", s, done=True)
        return self._finish(sid, s, self._out("intake_done", f"찾기 요청({sl['claim_id']})을 취소했어요. 방문 예약이 없어졌고, 물건은 본센터에 계속 보관돼요. "
                             "다시 찾으려면 분실 접수를 새로 해 주세요.", s, done=True,
                             ids={"claim_id": sl["claim_id"], "item_id": out.get("item_id")}))

    @staticmethod
    def _lost_text(sl: dict) -> str:
        bits = []
        if sl.get("when") not in (None, "모름"):
            bits.append(sl["when"])
        if sl.get("station") not in (None, "모름"):          # 11/10 역을 모르면 문장에서 뺀다('모름역에서'가 되던 것)
            bits.append(f"{sl['station']}역에서")
        if sl.get("color") not in (None, "모름"):
            bits.append(sl["color"])
        bits.append(category_label(sl["category"]))
        if sl.get("detail") not in (None, "모름", "없음"):
            bits.append(f"({sl['detail']})")
        return " ".join(bits) + " 잃어버렸어요"

    def _lost_result(self, sid: str, s: dict, res: dict) -> dict:
        if res.get("pending_id"):              # 후보를 가르려고 창구가 더 묻는다(확인 질문)
            s["stage"], s["pending_id"] = "quiz", res["pending_id"]
            self.sessions.put(sid, s)
            return self._out("intake_question", f"후보가 {len(res.get('candidates') or [])}개 있어요. {res['question']} (모르면 '모름')",
                             s, choices=["모름", "취소"])
        if res.get("waiting"):                 # 11/9 닮은 습득물이 아직 없음 → 대기로 받아 둠(분실인이 먼저 신고)
            wid = res["wait_id"]
            return self._finish(sid, s, self._out("intake_done", f"분실 신고를 대기로 받아 두었어요. 대기 번호 {wid}. 아직 닮은 습득물이 들어오지 않았는데, "
                                "들어오면 자동으로 찾기 번호가 만들어져요. 이 창에 대기 번호를 넣으면 상태를 알려 드려요.",
                                s, done=True, ids={"wait_id": wid, "story_id": res.get("story_id")}))
        if res.get("staff"):
            return self._finish(sid, s, self._out("intake_done", "닮은 후보가 여러 개라 자동으로 고르지 않았어요. 부산역 본센터 역무실에서 직원이 함께 확인해 드려요.",
                                s, done=True, ids={"story_id": res.get("story_id")}))
        cid = res["claim_id"]
        passed = res.get("quiz_passed")
        return self._finish(sid, s, self._out("intake_done", f"분실 접수가 끝났어요. 찾기 번호 {cid}. 부산역 본센터 키오스크 '물건 찾으러 왔어요'에서 "
                         f"찾기 번호와 신분증 번호 뒤 첫 자리({self._id_digit(s)})를 넣으면 로봇팔이 물건을 꺼내 드려요."
                         + ("" if passed else " 확인 질문이 맞지 않아 키오스크 대신 본센터 직원이 직접 확인한 뒤 꺼내 드려요.")
                         + f" 방문 전에 취소하려면 이 창에 '{cid} 취소'라고 말해 주세요.",
                         s, done=True, ids={"claim_id": cid, "story_id": res.get("story_id"), "item_id": res.get("item_id")}))

    @staticmethod
    def _id_digit(s: dict) -> str:
        m = re.match(r"^\*{6}-([1-4])\*{6}$", ((s.get("slots") or {}).get("identity") or {}).get("id_no_masked") or "")
        return m.group(1) if m else "신고할 때 고른 숫자"

    def _quiz_answer(self, sid: str, s: dict, q: str) -> dict:
        try:
            res = self.desk.answer(s["pending_id"], q or "모름")
        except Exception as e:
            self.sessions.drop(sid)
            msg = str(e) if type(e).__name__ in ("RequestError", "NotFound") else f"접수 창구 오류({type(e).__name__})"
            return self._out("intake_failed", f"접수하지 못했어요: {msg}", s, done=True)
        return self._lost_result(sid, s, res)

    # ---------- 응답 모양 ----------
    def _out(self, status: str, answer: str, s: dict | None, progress: bool = True, done: bool = False,
             choices: list | None = None, ids: dict | None = None) -> dict:
        info = None
        if s is not None:
            info = {"kind": s["kind"], "stage": "done" if done else s["stage"],
                    "filled": [k for k in self._order(s) if k in s["slots"]],
                    "missing": [k for k in self._order(s) if k not in s["slots"]],
                    "asked": None if done else s.get("asked"), "progress": progress, "draft_version": s.get("version", 0),
                    "filled_by": s["log"][-3:], **(ids or {})}
        return {"status": status, "answer": answer, "sources": [], "candidates": [], "choices": choices or [],
                "item_search_performed": False, "generation_used": False, "generation_status": "intake",
                "method": "conversational_intake", "scope": "대화 접수", "intake": info}


def check_action(action) -> dict | None:
    """위젯의 가린 본인 확인 또는 초안 확인 요청. 형식 오류는 ValueError → HTTP 422."""
    if action is None:
        return None
    if isinstance(action, dict) and action.get('type') == 'confirm':
        if (set(action) != {'type', 'draft_version', 'confirmation_token'}
                or type(action.get('draft_version')) is not int or not 0 <= action['draft_version'] <= 1000000
                or not isinstance(action.get('confirmation_token'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{43}', action['confirmation_token'])):
            raise ValueError('확인 요청의 초안 버전과 토큰 형식이 올바르지 않아요')
        return dict(action)
    if not isinstance(action, dict) or action.get("type") != "identity" or set(action) != {"type", "name_masked", "id_no_masked"}:
        raise ValueError('intake_action 은 가린 본인 확인(identity) 또는 초안 확인(confirm)만 받아요')
    nm, idm = action["name_masked"], action["id_no_masked"]
    if not (isinstance(nm, str) and "*" in nm and MASK_RE.match(nm)) or not (isinstance(idm, str) and ID_MASK_RE.match(idm)):
        raise ValueError("본인 확인 정보는 가린 값만 받아요(예: 홍*동, ******-1******)")
    return {"type": "identity", "name_masked": nm, "id_no_masked": idm}


__all__ = ["IntakeAgent", "IntakeSessions", "check_action", "detect_start", "extract"]
