"""에이전트 대화 — 메인 AI 아래에서 에이전트들이 요청·답·확인·채점·도움·되돌아보기를 주고받는다 (LF-14 · 11/9 변재원)

한줄 설명: 키오스크 AI·DB 에이전트·보관 칸 에이전트·로봇팔 에이전트가 메인 AI 를 거쳐 서로 필요한 정보를 묻고 답하며,
채점 에이전트가 답마다 점수를 매기고 부족하면 그 에이전트를 도와 더 나은 답을 다시 내게 한다. 도움받은 에이전트는
무엇이 부족했는지 스스로 정리하고(되돌아보기) 배운 점을 기억해 다음 답부터 반영한다.

방식(11/9 사용자 결정 '가'): 말은 정해진 틀, 채점은 규칙 — 그래픽카드(LLM)를 더 쓰지 않아 빠르고 늘 같은 결과.
- 모든 말은 메인 AI 를 거친다: 에이전트 → 메인 AI → 다른 에이전트 (메인 AI 가 요청을 나누고 답을 확인하고 결정)
- 채점 기준(grade): 필요한 항목을 다 채웠나(70점) + 코드가 다시 확인한 값과 맞나(30점). 개인정보 모양이 있으면 0점. 80점 미만이면 도움
- 안전 원칙은 그대로: 로봇을 움직일지는 코드가 정한다. 이 대화가 할 수 있는 일은 '멈추고 직원 확인'으로 더 조심하게 만드는 것뿐
- 보이는 곳: /live '에이전트 대화' 패널(말 하나씩) + 디스코드 🤖에이전트-대화 채널(대화 하나가 끝나면 한 번에, DISCORD_WEBHOOK_AGENT)

켜기: 가상 시연(TOWER_SIM=1)에서는 기본으로 켜짐. 끄려면 .env TOWER_AGENT_TALK=0
"""
from __future__ import annotations

import os
import threading

from agents.contracts import NONE, UNKNOWN, category_label, station_name

PASS = 80                         # 이 점수 미만이면 채점 에이전트가 돕는다
MAX_LINE = 220                    # 말 하나 최대 글자
MAX_DISCORD = 1900                # 디스코드 메시지 하나 최대 글자(2000 제한 안)

MAIN = "메인 AI"
KIOSK = "키오스크 AI"
DB = "DB 에이전트"
SLOT = "보관 칸 에이전트"
ROBOT = "로봇팔 에이전트"
GRADER = "채점 에이전트"

KINDS = {"request": "요청", "reply": "답", "check": "확인", "score": "점수", "coach": "도움",
         "reflect": "되돌아보기", "retry": "다시 답", "decide": "결정", "learn": "배운 점 반영"}
MARK = {"request": "📨", "reply": "💬", "check": "🔎", "score": "🧮", "coach": "🤝", "reflect": "💭",
        "retry": "🔁", "decide": "✅", "learn": "📚"}

# 에이전트가 배우는 것(되돌아보기 뒤 기억 → 다음 답부터 반영). 가상 세계 초기화 때 지움
LESSON_FULL_RECORD = "접수 표만 말고 특징·역 표도 함께 읽기"
LESSON_SLOT_BOUNDS = "칸 번호와 함께 칸 범위(mm)도 알려 주기"


def _known(v) -> bool:
    return v not in (None, "", UNKNOWN, NONE, [], {})


def _pii(text: str) -> list[str]:
    from discord_ops.reporter import find_pii
    return find_pii(text)


def grade(need: dict, got: dict, verify: dict | None = None) -> dict:
    """채점: need = {항목: 한국어 이름}, got = 답(항목 → 값), verify = {항목: 코드가 다시 본 값과 같은가(True/False)}.
    돌려줌 {"score", "missing"(빠진 항목 이름), "wrong"(틀린 항목 이름), "pii"}"""
    missing = [label for key, label in need.items() if not _known(got.get(key))]
    filled = len(need) - len(missing)
    checked = {k: v for k, v in (verify or {}).items() if v is not None}
    wrong = [need.get(k, k) for k, ok in checked.items() if ok is False]
    score = 70 * filled / max(1, len(need)) + (30 * (1 - len(wrong) / len(checked)) if checked else 30)
    pii = _pii(" ".join(str(v) for v in got.values()))
    return {"score": 0 if pii else round(score), "missing": missing, "wrong": wrong, "pii": pii}


class AgentTalk:
    """대화 기록·채점·도움·배운 점. 반환 흐름(supervisor)과 가상 시연 연출기(sim_director)가 부른다."""

    def __init__(self, reporter, board=None):
        self.rep = reporter
        self.board = board if board is not None else getattr(reporter, "board", None)
        self.lessons: dict[str, set] = {}
        self._lines: dict[str, list] = {}
        self._lock = threading.Lock()

    # ---------- 기록 ----------
    def say(self, key: str, frm: str, to: str, kind: str, text: str, score: int | None = None) -> None:
        """말 하나: /live 에는 바로, 디스코드에는 flush 때 대화 하나로 묶어서. 개인정보 모양이면 내용을 숨김"""
        text = " ".join(str(text or "").split())[:MAX_LINE]
        if _pii(f"{frm} {to} {text}"):
            text = "(개인정보로 보이는 글자가 있어 내용을 숨겼어요)"
        line = f"{MARK.get(kind, '•')} {frm} → {to} · {KINDS.get(kind, kind)}: {text}" + (f" [{score}점]" if score is not None else "")
        with self._lock:
            self._lines.setdefault(key, []).append(line)
        if self.board is not None:
            try:
                self.board.agent_say(frm, to, kind, text, score, ref=key)
            except Exception:
                pass

    def flush(self, key: str, title: str) -> None:
        """대화 하나가 끝남 → 디스코드 에이전트 채널로 한 번에(웹후크가 없으면 보내지 않음). 실패해도 흐름은 계속"""
        with self._lock:
            lines = self._lines.pop(key, [])
        if not lines:
            return
        body, used = [], 0
        for ln in lines:
            if used + len(ln) + 1 > MAX_DISCORD:
                body.append(f"… (말 {len(lines) - len(body)}개 더 — /live 에서 보기)")
                break
            body.append(ln)
            used += len(ln) + 1
        inner = getattr(self.rep, "inner", self.rep)          # /live 에는 이미 말 하나씩 보였으므로 디스코드에만
        try:
            inner.send("agent", f"[{key}] {title}", "\n".join(body))
        except Exception:
            pass

    def knows(self, agent: str, lesson: str) -> bool:
        return lesson in self.lessons.get(agent, set())

    def reset(self) -> None:
        with self._lock:
            self.lessons.clear()
            self._lines.clear()

    # ---------- 채점 → 도움 → 되돌아보기 → 다시 답 ----------
    def review(self, key: str, agent: str, need: dict, first: dict, verify: dict | None,
               improve, why_needed: str, lesson: str, cause: str, show=None) -> dict:
        """agent 의 답(first)을 채점하고, 기준 미만이면 메인 AI 가 채점 에이전트에게 도움을 부탁 → 채점 에이전트가 무엇이 왜 필요한지 알려 줌
        → agent 가 원인을 되돌아보고 배운 점을 기억 → improve() 로 다시 답 → 다시 채점. 돌려줌: 마지막 답"""
        g = grade(need, first, verify)
        self.say(key, GRADER, MAIN, "score", self._score_text(agent, g), g["score"])
        if g["score"] >= PASS or g["pii"]:
            return first
        self.say(key, MAIN, GRADER, "request", f"{agent} 답이 부족해요. 무엇이 왜 필요한지 알려 줘서 더 나은 답을 내게 도와줘")
        gaps = "·".join(g["missing"] + g["wrong"])
        self.say(key, GRADER, agent, "coach", f"빠졌거나 맞지 않은 항목: {gaps}. {why_needed}")
        self.say(key, agent, GRADER, "reflect", f"도움 고마워요. 제가 {cause} 그래서 {gaps} 항목을 놓쳤네요. "
                                                 f"앞으로는 '{lesson}' — 지금 다시 답할게요")
        with self._lock:
            self.lessons.setdefault(agent, set()).add(lesson)
        second = improve()
        g2 = grade(need, second, verify)
        self.say(key, agent, MAIN, "retry", (show or (lambda d: self._fields_text(need, d)))(second))
        self.say(key, GRADER, MAIN, "score", f"{agent} 다시 답 {g['score']}점 → {g2['score']}점"
                 + (" · 좋아졌어요" if g2["score"] > g["score"] else " · 그대로예요"), g2["score"])
        return second

    @staticmethod
    def _score_text(agent: str, g: dict) -> str:
        if g["pii"]:
            return f"{agent} 답에 개인정보 모양({'·'.join(g['pii'])})이 있어 0점 — 쓰지 않아요"
        parts = []
        if g["missing"]:
            parts.append("빠짐 " + "·".join(g["missing"]))
        if g["wrong"]:
            parts.append("불일치 " + "·".join(g["wrong"]))
        return f"{agent} 답 " + (" / ".join(parts) if parts else "필요한 항목을 모두 채웠고 확인 값과 일치")

    @staticmethod
    def _fields_text(need: dict, got: dict) -> str:
        return ", ".join(f"{label} {got.get(key)}" for key, label in need.items() if _known(got.get(key))) or "답할 내용 없음"

    # ================= 습득: 키오스크 AI → 메인 AI → DB 에이전트 =================
    NEED_FOUND = {"item_id": "물건 번호", "station": "역", "category": "품목", "color": "색", "status": "상태"}

    def found_registered(self, key: str, item: dict, place: str = "") -> dict:
        """특징 분석까지 끝난 습득물: 키오스크 AI 가 등록 확인을 부탁 → 메인 AI 가 DB 에이전트에게 기록을 물음 → 채점·도움 → 메인 AI 확인.
        item = DB 기록(db_get_item 모양). 돌려줌: DB 에이전트의 마지막 답"""
        f = item.get("features") or {}
        machine = item.get("machine_id") or ""
        station = station_name(machine, item.get("item_id")) or ""
        cat = category_label(f.get("category")) if _known(f.get("category")) else ""
        color = f.get("color") if _known(f.get("color")) else ""
        self.say(key, KIOSK, MAIN, "request",
                 f"{station or '역 미상'} 등록기계 접수 · 장소 '{place or '미입력'}' · 사진 분석 {cat or '품목 확인 불가'}"
                 + (f"·{color}" if color else "") + f" — {item.get('item_id')} 물건이 등록됐는지 확인해 주세요")
        self.say(key, MAIN, DB, "request", f"{item.get('item_id')} 기록을 알려 줘(필요: 역·품목·색·상태)")
        full = {"item_id": item.get("item_id"), "station": station, "category": cat, "color": color or "확인 불가",
                "status": item.get("status")}
        if self.knows(DB, LESSON_FULL_RECORD):
            first = full
            self.say(key, DB, MAIN, "learn", f"지난번 도움 반영: {LESSON_FULL_RECORD}")
        else:     # 처음에는 접수 표(물건 번호·등록기계·상태)만 읽는다 — 채점 에이전트 도움으로 특징·역 표까지 읽게 됨
            first = {"item_id": item.get("item_id"), "machine": machine, "status": item.get("status")}
        self.say(key, DB, MAIN, "reply", self._fields_text(self.NEED_FOUND, first) + (f", 등록기계 {machine}" if first.get("machine") else ""))
        verify = {"station": (first.get("station") == station) if _known(first.get("station")) else None,
                  "category": (first.get("category") == cat) if _known(first.get("category")) else None}
        last = self.review(key, DB, self.NEED_FOUND, first, verify, lambda: full,
                           "메인 AI 가 보관 칸을 고르려면 품목이, 분실인이 검색하려면 역·색이 필요해요. 특징 표와 역 표도 함께 읽어 주세요",
                           LESSON_FULL_RECORD, "접수 표만 읽고 답했어요.")
        ok = last.get("category") == cat and last.get("station") == station
        self.say(key, MAIN, KIOSK, "check",
                 f"키오스크 요청과 DB 기록이 맞아요({station} · {cat or '품목 확인 불가'}) — 보관 칸을 잡을게요" if ok
                 else "키오스크 요청과 DB 기록이 달라요 — 직원 확인을 부를게요")
        return last

    # ================= 습득: 메인 AI → 보관 칸 에이전트 =================
    def slot_reserved(self, key: str, item_id: str, category: str | None, slot: str | None, allowed: list | None,
                      wait_no: int | None = None) -> None:
        cat = category_label(category) if _known(category) else "품목 확인 불가"
        self.say(key, MAIN, SLOT, "request", f"{item_id} 물건({cat})이 들어갈 빈 칸을 잡아 줘")
        if slot:
            self.say(key, SLOT, MAIN, "reply", f"{slot} 칸을 잡았어요(이 열: {'·'.join(category_label(c) for c in (allowed or [])) or '모든 품목'})")
            ok = not allowed or category in allowed
            g = grade({"slot": "칸 번호", "category_ok": "품목 맞는 열"}, {"slot": slot, "category_ok": ok}, {"category_ok": ok})
            self.say(key, GRADER, MAIN, "score", self._score_text(SLOT, g), g["score"])
            self.say(key, MAIN, SLOT, "decide", f"{slot} 칸이 {cat} 열이 맞아요 — 회수해서 그 칸에 둘게요" if ok
                     else f"{slot} 칸은 {cat} 열이 아니에요 — 직원 확인")
        else:
            self.say(key, SLOT, MAIN, "reply", f"{cat} 열에 빈 칸이 없어요" + (f" — 칸 대기 {wait_no}번째" if wait_no else ""))
            self.say(key, MAIN, SLOT, "decide", "회수하지 않고 등록기계에 둘게요. 칸이 비면 먼저 온 순서대로 회수하고, 직원에게 알렸어요")

    def stored(self, key: str, item_id: str, slot: str) -> None:
        self.say(key, MAIN, KIOSK, "decide", f"{item_id} 물건을 {slot} 칸에 보관했어요 — 분실 신고가 오면 반환할 수 있어요")
        self.flush(key, f"습득 {item_id} 에이전트 대화")

    # ================= 반환: 로봇팔 에이전트 → 메인 AI → DB 에이전트 =================
    NEED_SLOT = {"slot_id": "칸 번호", "bounds": "칸 범위(mm)"}

    def robot_check(self, key: str, item_id: str, target_mm, slot_area: dict | None) -> str:
        """로봇이 접근하기 전에: 로봇팔 에이전트가 메인 AI 를 거쳐 DB 에이전트에게 칸·칸 범위를 묻고, 탑뷰 물건 중심이 그 안인지 확인.
        돌려줌: "" = 진행해도 됨(원래 기준), 글 = 멈추고 직원 확인할 이유(더 조심하는 쪽으로만)"""
        x, y = float(target_mm[0]), float(target_mm[1])
        self.say(key, ROBOT, MAIN, "request", f"{item_id} 물건을 집으러 가기 전에 보관 칸과 칸 범위를 알려 주세요(탑뷰 좌표 {x:.0f},{y:.0f}mm 와 맞춰 볼게요)")
        self.say(key, MAIN, DB, "request", f"{item_id} 의 보관 칸 번호와 칸 범위(mm)를 알려 줘")
        area = slot_area or {}
        b = area.get("bounds_mm")
        bounds = list(b) if isinstance(b, (list, tuple)) and len(b) == 4 else None
        full = {"slot_id": area.get("slot_id"), "bounds": bounds}
        if not area.get("slot_id"):
            self.say(key, DB, MAIN, "reply", "이 물건의 보관 칸 기록이 없어요")
            self.say(key, MAIN, ROBOT, "decide", "칸 기록이 없어 위치로는 확인할 수 없어요 — 매칭 결과만으로 진행(원래 기준)")
            return ""
        if self.knows(DB, LESSON_SLOT_BOUNDS):
            first = full
            self.say(key, DB, MAIN, "learn", f"지난번 도움 반영: {LESSON_SLOT_BOUNDS}")
        else:     # 처음에는 칸 번호만 — 로봇이 위치를 맞춰 보려면 범위가 필요하다는 것을 채점 에이전트 도움으로 배움
            first = {"slot_id": area.get("slot_id")}
        self.say(key, DB, MAIN, "reply", self._bounds_text(first))
        last = self.review(key, DB, self.NEED_SLOT, first, None, lambda: full,
                           "로봇팔이 탑뷰 좌표와 맞춰 보려면 칸 범위(mm)가 필요해요. 칸 기록과 함께 구역 좌표도 읽어 주세요",
                           LESSON_SLOT_BOUNDS, "칸 번호만 알려 드렸어요.", show=self._bounds_text)
        bounds = last.get("bounds")
        self.say(key, MAIN, ROBOT, "reply", self._bounds_text(last))
        if not bounds:
            self.say(key, ROBOT, MAIN, "check", "칸 범위가 없어 위치로는 확인할 수 없어요")
            self.say(key, MAIN, ROBOT, "decide", "매칭 결과만으로 진행(원래 기준)")
            return ""
        x0, y0, x1, y1 = (float(v) for v in bounds)
        inside = x0 <= x <= x1 and y0 <= y <= y1
        self.say(key, ROBOT, MAIN, "check", f"탑뷰 물건 중심 ({x:.0f},{y:.0f})mm → {last['slot_id']} 칸 범위 "
                 + ("안이에요 ✓" if inside else "밖이에요 ✗"))
        if inside:
            self.say(key, MAIN, ROBOT, "decide", "기록 칸과 탑뷰 위치가 맞아요 — 사전 접근 시작해")
            return ""
        self.say(key, MAIN, ROBOT, "decide", "기록 칸과 탑뷰 위치가 달라요 — 로봇을 움직이지 않고 직원 확인을 부를게요")
        return f"기록 칸 {last['slot_id']} 와 탑뷰 위치가 다름 — 로봇을 움직이지 않음"

    @staticmethod
    def _bounds_text(got: dict) -> str:
        b = got.get("bounds")
        return f"{got.get('slot_id')} 칸" + (f", 범위 x {b[0]:.0f}~{b[2]:.0f} · y {b[1]:.0f}~{b[3]:.0f}mm" if b else "")

    def return_done(self, key: str, item_id: str, decision: str, reason: str) -> None:
        ko = {"returned": "반환 완료(제출보관함)", "staff_check": "직원 확인", "rejected": "반환 안 함", "stopped": "로봇 정지"}.get(decision, decision)
        self.say(key, MAIN, ROBOT, "decide", f"{item_id} {ko}" + (f" — {reason}" if reason and decision != "returned" else ""))
        self.flush(key, f"반환 {item_id} 에이전트 대화")

    # ================= 관제탑 메인 AI(TowerBrain) 대화도 같은 곳에 =================
    def brain_said(self, key: str, who: str, text: str) -> None:
        """TowerBrain._say 를 에이전트 대화로도: '메인 AI' 의 '→ ○○ 에이전트: …' 는 요청, 에이전트 말은 메인 AI 에게 답"""
        if who == MAIN and text.startswith("→ ") and ":" in text:
            to, rest = text[2:].split(":", 1)
            self.say(key, MAIN, to.strip(), "request", rest.strip())
        elif who == MAIN:
            self.say(key, MAIN, ROBOT if text.startswith("결론") else MAIN, "decide" if text.startswith("결론") else "check", text)
        else:
            self.say(key, who, MAIN, "reply", text)


def build_talk(reporter, env: dict | None = None, sim: bool = False) -> AgentTalk | None:
    """TOWER_AGENT_TALK=1 이거나(가상 시연이면 기본 켜짐) → AgentTalk. 0 이면 끔"""
    env = os.environ if env is None else env
    v = (env.get("TOWER_AGENT_TALK") or "").strip()
    if v == "0" or (not sim and v != "1"):
        return None
    return AgentTalk(reporter)


__all__ = ["AgentTalk", "grade", "build_talk", "PASS", "KINDS", "LESSON_FULL_RECORD", "LESSON_SLOT_BOUNDS"]
