"""에이전트 대화 — 메인 AI 아래에서 에이전트들이 요청·답·확인·채점·도움·되돌아보기를 주고받는다 (LF-14 · 11/9 변재원)

한줄 설명: 키오스크 AI·DB 에이전트·보관 칸 에이전트·로봇팔 에이전트가 메인 AI 를 거쳐 서로 필요한 정보를 묻고 답하며,
채점 에이전트가 그 답을 **다른 기록(보관함 정답지·등록기계 역 표·탑뷰 위치)으로 다시 맞춰 보고**, 어긋나면 무엇이 왜 문제인지
알려 직원 확인을 부른다.

11/11 사용자 결정(채점 에이전트 존재 의의 검토 → 2번 '실제 검증 위주'): 예전에는 DB 에이전트의 첫 답을 일부러 덜 채워
'점수 낮음 → 도움 → 되돌아보기 → 배운 점' 을 매번 연출했다(실제로 잡는 것은 개인정보·위치 불일치뿐). 이제 연출을 없애고
실제로 틀릴 수 있는 것을 검사한다 — 사진 분석이 품목·색을 못 읽음 · 운영하지 않는 품목 · 적은 장소와 등록기계 역이 다름 ·
보관 칸이 다른 열/이미 찬 칸/먼 줄(-1)을 건너뜀 · 정답지에 빈 칸이 있는데 칸 대기 · 탑뷰 위치가 칸 범위 밖

방식(11/9 사용자 결정 '가'): 말은 정해진 틀, 채점은 규칙 — 그래픽카드(LLM)를 더 쓰지 않아 빠르고 늘 같은 결과.
- 모든 말은 메인 AI 를 거친다: 에이전트 → 메인 AI → 다른 에이전트 (메인 AI 가 요청을 나누고 답을 확인하고 결정)
- 채점 기준(grade): 필요한 항목을 다 채웠나(70점) + 다른 기록과 맞나(30점). 개인정보 모양이 있으면 0점.
  빠지거나 어긋난 항목이 하나라도 있으면 도움(무엇이 왜 문제인지) + 직원 확인 경보 — 점수는 보여 주기용
- 안전 원칙은 그대로: 로봇을 움직일지는 코드가 정한다. 이 대화가 할 수 있는 일은 '멈추고 직원 확인'으로 더 조심하게 만드는 것뿐
- 보이는 곳: /live '에이전트 대화' 패널(말 하나씩) + 디스코드 🤖에이전트-대화 채널(대화 하나가 끝나면 한 번에, DISCORD_WEBHOOK_AGENT)

켜기: 가상 시연(TOWER_SIM=1)에서는 기본으로 켜짐. 끄려면 .env TOWER_AGENT_TALK=0
"""
from __future__ import annotations

import os
import re
import threading

from agents.contracts import MACHINE_STATION_NAME, NONE, UNKNOWN, category_label, is_active_category, station_name

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
         "reflect": "되돌아보기", "retry": "다시 답", "decide": "결정", "learn": "배운 점 반영", "explain": "설명(sLLM)"}
MARK = {"request": "📨", "reply": "💬", "check": "🔎", "score": "🧮", "coach": "🤝", "reflect": "💭",
        "retry": "🔁", "decide": "✅", "learn": "📚", "explain": "🗣"}



def _known(v) -> bool:
    return v not in (None, "", UNKNOWN, NONE, [], {})


def _pii(text: str) -> list[str]:
    from discord_ops.reporter import find_pii
    return find_pii(text)


def _station_in(place: str) -> str:
    """적은 장소 글에 나온 역 이름(등록기계 역 표 기준). 없으면 빈 글자. 예: '초량역 5번 출구' → '초량역'"""
    place = str(place or "")
    for name in MACHINE_STATION_NAME.values():
        short = name.split()[0].removesuffix("역")
        if short and short in place:
            return name
    return ""


def _occupant(layout: dict, slot_id: str):
    for sec in layout.get("sections", []):
        for sl in sec.get("slots", []):
            if sl.get("slot_id") == slot_id:
                return (sl.get("item") or {}).get("item_id")
    return None


def _free_slots(layout: dict, category, item_id: str, held: set | None) -> list:
    """보관함 정답지에서 이 품목을 받는 로봇 칸 중 빈 칸(이 물건 자신이 있는 칸 포함, 다른 물건이 잡아 둔 칸 제외)"""
    out = []
    for sec in layout.get("sections", []):
        allowed = sec.get("allowed_categories") or []
        if sec.get("kind") != "shelf" or (allowed and category not in allowed):
            continue
        for sl in sec.get("slots", []):
            who = (sl.get("item") or {}).get("item_id")
            if who in (None, item_id) and sl.get("slot_id") not in (held or set()):
                out.append(sl["slot_id"])
    return out


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
        self.alerts = reporter      # 직원 확인 경보는 처음 받은 reporter 로(시연 도구가 rep 를 디스코드 전송용으로 바꿔도 경보 채널로는 안 보냄)
        self.board = board if board is not None else getattr(reporter, "board", None)
        self._lines: dict[str, list] = {}
        self._lock = threading.Lock()
        self.explainer = None       # 11/12 메인 AI 결정을 쉬운 한 문장으로 풀어 주는 sLLM(make_explainer) — 없으면 규칙 문장만
        self._explaining = threading.Lock()

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
        if kind == "decide" and frm == MAIN and self.explainer is not None:
            self._explain_later(key, to, text)

    def _explain_later(self, key: str, to: str, decision: str) -> None:
        """11/12 메인 AI 결정 → sLLM 이 '왜'를 쉬운 한 문장으로(뒤에서, 흐름을 막지 않음). 한 번에 하나만 — 이미 만드는 중이면 건너뜀.
        결정 문장에 없는 숫자·칸 번호를 만들어 내거나 개인정보 모양이면 버린다(규칙 문장이 사실, 설명은 덧붙임)"""
        if not self._explaining.acquire(blocking=False):
            return

        def run():
            try:
                out = safe_explanation(self.explainer(decision), decision)
                if out and self.board is not None:
                    self.board.agent_say(MAIN, to, "explain", out, None, ref=key)
            except Exception:
                pass
            finally:
                self._explaining.release()
        threading.Thread(target=run, daemon=True, name="agent-explain").start()

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

    def reset(self) -> None:
        with self._lock:
            self._lines.clear()

    # ---------- 채점 → (문제가 있으면) 도움 → 직원 확인 ----------
    def judge(self, key: str, agent: str, need: dict, got: dict, verify: dict | None, why: dict, case: str | None = None,
              alert: bool = True) -> dict:
        """agent 의 답(got)을 채점. verify 는 코드가 **다른 기록(보관함 정답지·등록기계 표 등)** 으로 다시 본 결과.
        빠진 항목이 있거나 다시 본 값과 다르면: 채점 에이전트가 무엇이 왜 문제인지 알리고(도움) → 메인 AI 가 직원 확인 경보.
        11/11 사용자 결정(2번): 예전에는 첫 답을 **일부러** 덜 채워 '도움 → 배운 점' 을 매번 연출했다 → 없앰. 이제는 실제로 틀릴 때만 도움.
        why = {항목 이름: 그 항목이 왜 필요한지/틀리면 무슨 일이 생기는지}. 돌려줌: grade 결과 + "flag"(직원 확인이 필요한가)"""
        # 11/12 사용자 결정: 채점 에이전트(점수)는 없앰 — 다른 기록과 맞춰 보는 실제 검사는 메인 AI 가 직접 하고 결과만 한 줄로
        g = grade(need, got, verify)
        gaps = g["missing"] + g["wrong"]
        g["flag"] = bool(gaps) or bool(g["pii"])
        if g["pii"]:
            self.say(key, MAIN, agent, "check", f"{agent} 답에 개인정보 모양이 있어 쓰지 않아요")
        elif gaps:
            self.say(key, MAIN, agent, "check", "다른 기록과 맞춰 보니 확인할 점이 있어요 — "
                     + " ".join(f"{name}: {why.get(name, '확인 필요')}." for name in gaps))
        else:
            self.say(key, MAIN, agent, "check", f"{agent} 답을 다른 기록(보관함 정답지·등록기계 역 표)과 맞춰 봤어요 — 일치")
        if gaps and alert:
            try:
                self.alerts.alert(case or key, f"{agent} 답 확인 필요 — {'·'.join(gaps)}", "에이전트 대화에서 메인 AI 가 찾음(/live)")
            except Exception:
                pass
        return g

    @staticmethod
    def _score_text(agent: str, g: dict) -> str:
        if g["pii"]:
            return f"{agent} 답에 개인정보 모양({'·'.join(g['pii'])})이 있어 0점 — 쓰지 않아요"
        parts = []
        if g["missing"]:
            parts.append("빠짐 " + "·".join(g["missing"]))
        if g["wrong"]:
            parts.append("불일치 " + "·".join(g["wrong"]))
        return f"{agent} 답 " + (" / ".join(parts) if parts else "필요한 항목을 모두 채웠고 다른 기록과도 일치")

    @staticmethod
    def _fields_text(need: dict, got: dict) -> str:
        return ", ".join(f"{label} {got.get(key)}" for key, label in need.items() if _known(got.get(key))) or "답할 내용 없음"

    # ================= 습득: 키오스크 AI → 메인 AI → DB 에이전트 =================
    NEED_FOUND = {"item_id": "물건 번호", "station": "역", "category": "품목", "color": "색", "status": "상태"}
    WHY_FOUND = {"역": "적은 장소가 등록기계 역과 다르면 분실인 검색·확인 질문(장소)이 어긋나요",
                 "품목": "품목을 모르거나 운영 품목(목업폰·보조배터리·핸드크림·립밤)이 아니면 보관 칸 열을 고를 수 없어요 — 사진을 직원이 봐야 해요",
                 "색": "색을 모르면 분실인이 색으로 찾거나 확인할 수 없어요",
                 "물건 번호": "번호가 없으면 기록을 이을 수 없어요", "상태": "상태가 없으면 회수 여부를 정할 수 없어요"}

    def found_registered(self, key: str, item: dict, place: str = "") -> dict:
        """특징 분석까지 끝난 습득물: 키오스크 AI 가 등록 확인을 부탁 → 메인 AI 가 DB 에이전트에게 기록을 물음 → 채점.
        실제 검사(11/11): ① 품목·색이 채워졌나(사진 분석 실패) ② 품목이 운영 품목인가 ③ 적은 장소의 역이 등록기계 역과 같은가.
        item = DB 기록(db_get_item 모양). 돌려줌: DB 에이전트의 답 + "grade" """
        f = item.get("features") or {}
        machine = item.get("machine_id") or ""
        station = station_name(machine, item.get("item_id")) or ""
        cat = category_label(f.get("category")) if _known(f.get("category")) else ""
        color = f.get("color") if _known(f.get("color")) else ""
        self.say(key, KIOSK, MAIN, "request",
                 f"{station or '역 미상'} 등록기계 접수 · 장소 '{place or '미입력'}' · 사진 분석 {cat or '품목 확인 불가'}"
                 + (f"·{color}" if color else "") + f" — {item.get('item_id')} 물건이 등록됐는지 확인해 주세요")
        self.say(key, MAIN, DB, "request", f"{item.get('item_id')} 기록을 알려 줘(필요: 역·품목·색·상태)")
        got = {"item_id": item.get("item_id"), "station": station, "category": cat, "color": color, "status": item.get("status")}
        self.say(key, DB, MAIN, "reply", self._fields_text(self.NEED_FOUND, got))
        said = _station_in(place)
        verify = {"category": is_active_category(f.get("category")) if cat else None,
                  "station": (said == station) if said and station else None}
        g = self.judge(key, DB, self.NEED_FOUND, got, verify, self.WHY_FOUND, item.get("item_id"))
        self.say(key, MAIN, KIOSK, "check",
                 f"키오스크 요청과 DB 기록이 맞아요({station} · {cat}) — 보관 칸을 잡을게요" if not g["flag"]
                 else "확인이 필요한 항목이 있어요 — 직원에게 알렸어요(접수는 그대로 진행)")
        return {**got, "grade": g}

    # ================= 습득: 메인 AI → 보관 칸 에이전트 =================
    WHY_SLOT = {"품목 맞는 열": "품목이 다른 열에 넣으면 로봇이 엉뚱한 칸에서 집어요",
                "빈 칸": "보관함 정답지(DB)에 이미 다른 물건이 있는 칸이에요 — 두 물건이 한 칸에 겹쳐요",
                "먼 줄 먼저": "같은 열의 먼 줄(-1) 칸이 비어 있어요 — 먼 줄(1·3·5·7)부터 채우는 규칙",
                "칸 대기 판단": "보관함 정답지(DB)에는 이 품목 열에 빈 칸이 있어요 — 칸 기록이 실물과 어긋났을 수 있어요"}

    def slot_reserved(self, key: str, item_id: str, category: str | None, slot: str | None, allowed: list | None,
                      wait_no: int | None = None, layout: dict | None = None, held: set | None = None) -> dict:
        """보관 칸 에이전트(가상 세계의 칸 고르기)의 답을 **보관함 정답지(storage, DB 와 같은 규칙)** 로 다시 본다(11/11).
        layout = storage.layout(), held = 다른 물건이 회수하려고 잡아 둔 칸(정답지에는 아직 안 보임).
        검사: ① 품목 맞는 열 ② 정답지에서 빈 칸 ③ 먼 줄(-1) 먼저 ④ 칸 대기인데 정답지에 빈 칸이 있으면 이상. 돌려줌: grade 결과"""
        cat = category_label(category) if _known(category) else "품목 확인 불가"
        free = _free_slots(layout, category, item_id, held) if layout else None
        self.say(key, MAIN, SLOT, "request", f"{item_id} 물건({cat})이 들어갈 빈 칸을 잡아 줘")
        if slot:
            self.say(key, SLOT, MAIN, "reply", f"{slot} 칸을 잡았어요(이 열: {'·'.join(category_label(c) for c in (allowed or [])) or '모든 품목'})")
            col_ok = not allowed or category in allowed
            occupant = _occupant(layout, slot) if layout else None
            empty_ok = None if not layout else occupant in (None, item_id)
            near = slot.rsplit("-", 1)[0] + "-1"
            order_ok = None if free is None else not (slot.endswith("-2") and near in free)
            need = {"slot": "칸 번호", "column": "품목 맞는 열", "empty": "빈 칸", "order": "먼 줄 먼저"}
            g = self.judge(key, SLOT, need, {"slot": slot, "column": col_ok, "empty": empty_ok, "order": order_ok},
                           {"column": col_ok, "empty": empty_ok, "order": order_ok}, self.WHY_SLOT, item_id)
            self.say(key, MAIN, SLOT, "decide", f"{slot} 칸이 {cat} 열의 알맞은 빈 칸이에요 — 회수해서 그 칸에 둘게요" if not g["flag"]
                     else f"{slot} 칸에 확인할 점이 있어요 — 직원 확인(보관 화면에서 칸을 다시 보세요)")
            return g
        self.say(key, SLOT, MAIN, "reply", f"{cat} 열에 빈 칸이 없어요" + (f" — 칸 대기 {wait_no}번째" if wait_no else ""))
        wait_ok = None if free is None or not _known(category) else not free
        g = self.judge(key, SLOT, {"wait": "칸 대기 판단"}, {"wait": "칸 대기"}, {"wait": wait_ok}, self.WHY_SLOT, item_id)
        self.say(key, MAIN, SLOT, "decide", "회수하지 않고 등록기계에 둘게요. 칸이 비면 먼저 온 순서대로 회수하고, 직원에게 알렸어요"
                 if not g["flag"] else f"정답지에는 빈 칸({'·'.join(free)})이 있어요 — 직원 확인(보관 화면 칸 기록 확인)")
        return g

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
        self.say(key, DB, MAIN, "reply", self._bounds_text(full))
        last = full
        bounds = last.get("bounds")
        if not bounds:
            self.say(key, ROBOT, MAIN, "check", "칸 범위가 없어 위치로는 확인할 수 없어요")
            self.say(key, MAIN, ROBOT, "decide", "매칭 결과만으로 진행(원래 기준)")
            return ""
        x0, y0, x1, y1 = (float(v) for v in bounds)
        inside = x0 <= x <= x1 and y0 <= y <= y1
        self.say(key, ROBOT, MAIN, "check", f"탑뷰 물건 중심 ({x:.0f},{y:.0f})mm → {last['slot_id']} 칸 범위 "
                 + ("안이에요 ✓" if inside else "밖이에요 ✗"))
        self.judge(key, DB, self.NEED_SLOT, last, {"bounds": inside},
                   {"칸 범위(mm)": "DB 칸 기록과 탑뷰가 본 물건 위치가 달라요 — 다른 물건을 집을 수 있어요"}, item_id,
                   alert=False)                                   # 경보는 반환 흐름(supervisor)이 직원 확인으로 한 번 보냄
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


EXPLAIN_SYSTEM = ("너는 지하철 분실물 관제탑의 메인 AI다. 아래 결정을 처음 보는 관람객이 이해하도록 '왜 그렇게 했는지'를 "
                  "한국어 존댓말 한 문장(60자 이내)으로 쉽게 설명해. 결정에 없는 숫자·칸 번호·사실은 만들지 마. 설명 문장만 써.")


def safe_explanation(text, decision: str) -> str:
    """sLLM 설명 검사: 한 문장·짧게, 결정에 없는 숫자/칸 번호(R1-1 등)·개인정보 모양이면 버림("")"""
    t = " ".join(str(text or "").split()).strip().strip('"').strip()
    if not t or not re.search(r"[가-힣]", t) or _pii(t):
        return ""
    t = re.split(r"(?<=[.!?])\s", t)[0]
    if len(t) > 90:
        return ""
    for tok in re.findall(r"[A-Z]\d-\d|\d+", t):
        if tok not in decision:
            return ""
    return t


def make_explainer(env: dict | None = None):
    """로컬 sLLM(Ollama)로 설명을 만드는 함수. 모델은 TOWER_AGENT_LLM_MODEL → LF_CHAT_RAG_MODEL → midm-2.0-mini.
    Qwen 사진 분석 등이 그래픽카드 사용권을 쥐고 있으면 이번엔 건너뜀(분석을 늦추지 않게). 실패하면 예외 → 설명 없이 진행"""
    env = os.environ if env is None else env
    model = (env.get("TOWER_AGENT_LLM_MODEL") or env.get("LF_CHAT_RAG_MODEL") or "midm-2.0-mini").strip()

    def explain(decision: str) -> str:
        from agents.local_model import ask_local_model, gpu_taken
        if gpu_taken():
            return ""
        r = ask_local_model({"model": model, "stream": False, "keep_alive": "5m",
                             "options": {"temperature": 0.2, "num_predict": 80},
                             "messages": [{"role": "system", "content": EXPLAIN_SYSTEM},
                                          {"role": "user", "content": f"결정: {decision}"}]}, timeout=12)
        return ((r or {}).get("message") or {}).get("content") or ""
    explain.model = model
    return explain


def build_talk(reporter, env: dict | None = None, sim: bool = False) -> AgentTalk | None:
    """TOWER_AGENT_TALK=1 이거나(가상 시연이면 기본 켜짐) → AgentTalk. 0 이면 끔.
    11/12 메인 AI 결정 설명(sLLM)은 기본 켜짐 — 끄기 TOWER_AGENT_LLM=0(Ollama 가 꺼져 있으면 저절로 설명 없이)"""
    env = os.environ if env is None else env
    v = (env.get("TOWER_AGENT_TALK") or "").strip()
    if v == "0" or (not sim and v != "1"):
        return None
    talk = AgentTalk(reporter)
    if str(env.get("TOWER_AGENT_LLM", "1")).strip().lower() not in ("0", "false", "no", "off"):
        talk.explainer = make_explainer(env)
    return talk


__all__ = ["AgentTalk", "grade", "build_talk", "make_explainer", "safe_explanation", "PASS", "KINDS"]
