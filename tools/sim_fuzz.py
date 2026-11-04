"""가상 시연 무작위 시험 — 디스코드 봇과 같은 입구로 습득·분실·확인 질문·정지·초기화를 무작위로 섞어 돌리고, 매번 규칙을 검사한다 (LF-29, 11/4).

한줄 설명: 사람이 100번 눌러 보는 대신, 무작위 메시지 수백 개를 넣어 "물건이 사라지거나 둘이 되지 않는가, 엉뚱한 물건을 돌려주지 않는가,
           개인정보가 관제 메시지에 섞이지 않는가, 로봇이 멈춘 채로 남지 않는가"를 자동으로 확인한다.

사용법 (저장소 폴더, .venv 켠 상태 — 관제탑을 켜지 않아도 됨, 디스코드로 아무것도 보내지 않음)
    python tools/sim_fuzz.py                 # 무작위 이야기 120개(시간 지연 없음)
    python tools/sim_fuzz.py --runs 300 --seed 7
    python tools/sim_fuzz.py --timed 20      # 시간 지연을 켠 회차 20개(반환 도중 정지 버튼 시험 포함)

- 같은 --seed 면 같은 순서로 다시 돌릴 수 있다(문제 재현용)
- 결과: 위반이 없으면 "위반 0건", 있으면 회차·메시지 종류·위반 내용(개인정보 없이)
"""
from __future__ import annotations

import argparse
import os
import random
import re
import sys
import threading
import time
from collections import Counter

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import HANDOVER_DONE, HANDOVER_HOLD, HANDOVER_WAIT  # noqa: E402
from agents.service import Conflict, NotFound, RequestError, Unavailable  # noqa: E402
from agents.sim_director import build_sim_service  # noqa: E402
from discord_ops.reporter import find_pii  # noqa: E402
from tools.lostfound_bot import BotCore, TowerError, classify, progress_text  # noqa: E402

STATIONS = ["서면역", "해운대역", "중앙역", "부산역", "서면", ""]
PLACES = ["5번 출구 앞", "승강장", "화장실 앞", "개찰구 옆", "엘리베이터 안", "의자 밑", ""]
ITEMS = ["카드지갑", "지갑", "반지갑", "USB", "유에스비", "보조배터리", "립밤", "핸드크림", "모형폰", "휴대폰", "우산", "열쇠", ""]
COLORS = ["검정", "까만", "브라운", "갈색", "분홍", "핑크샌드", "흰색", "화이트", "은색", "파란", "블루", "빨간", "노란", ""]
EXTRAS = ["", "", "SanDisk 글자", "'VOVA' 글자", "별 스티커", "스티커 없어요", "가죽", "플라스틱", "#집기실패", "#보정실패",
          "#신분증불일치", "#수동인계", "#집기실패 #보정실패", "😀😀", "010-1234-5678", "a" * 280]
ANSWERS = ["SanDisk", "sandisk", "모름", "Kingston", "", "없어요", "VOVA", "별", "010-9999-8888",
           "서면역", "해운대", "중앙역", "부산역", "검정", "브라운", "분홍", "흰색", "파란색"]
COMMANDS = ["상태", "도움말", "!도움말", "정지", "원점", "초기화", "help", "안녕", "?", ""]
LOC_OK = {  # 물건 상태 → 있을 수 있는 실제 위치
    "등록기계 보관": {"kiosk"}, "회수 중": {"transit"}, "본센터 보관": {"bin"}, "확인 중": {"bin"},
    "승인·수령 예약": {"bin"}, "반환 중": {"bin", "gripper", "staff", "basket"}, HANDOVER_WAIT: {"basket"},
    HANDOVER_DONE: {"handed"}, HANDOVER_HOLD: {"bin", "staff", "basket"}}


class InProcClient:
    """분실물 봇의 TowerClient 와 같은 모양(post/get)으로 관제탑 서비스를 바로 부른다(HTTP 없이)."""

    def __init__(self, svc):
        self.svc = svc

    def _wrap(self, fn, *a):
        try:
            return fn(*a)
        except (RequestError, NotFound, Conflict, Unavailable) as e:
            raise TowerError(str(e)) from e

    def post(self, path, body=None):
        d, body = self.svc.sim, body or {}
        if path == "/sim/found":
            return self._wrap(d.found, body["text"])
        if path == "/sim/lost":
            return self._wrap(d.lost, body["text"])
        m = re.match(r"^/sim/lost/([^/]+)/answer$", path)
        if m:
            return self._wrap(d.answer, m.group(1), body["text"])
        if path == "/robot/stop":
            return self.svc.stop_robot()
        if path == "/robot/home":
            return self._wrap(self.svc.robot_home, body)
        if path == "/sim/reset":
            if self.svc.health()["busy"]:
                raise TowerError("반환 진행 중 — 끝난 뒤 초기화")
            return d.reset()
        raise TowerError(f"모르는 경로 {path}")

    def get(self, path):
        if path.startswith("/live/state"):
            return {"busy": self.svc.health()["busy"], "world": self.svc.world.snapshot()}
        m = re.match(r"^/sim/stories/([^/?]+)", path)
        if m:
            st = self.svc.board.story(m.group(1))
            if st is None:
                raise TowerError("없는 이야기 번호")
            return st
        raise TowerError(f"모르는 경로 {path}")


def rand_message(rng: random.Random) -> str:
    kind = rng.random()
    if kind < 0.38:      # 습득
        st, pl, it, co, ex = (rng.choice(x) for x in (STATIONS, PLACES, ITEMS, COLORS, EXTRAS))
        verb = rng.choice(["주웠어요", "발견했어요", "에 떨어져 있었어요", "습득했습니다"])
        sep = rng.choice(["에서 ", " ", "에서 "])
        return f"{st} {pl}{sep}{co} {it} {ex} {verb}".strip()
    if kind < 0.80:      # 분실
        co, it, ex, st = (rng.choice(x) for x in (COLORS, ITEMS, EXTRAS, STATIONS))
        verb = rng.choice(["잃어버렸어요", "분실했어요", "찾고 있어요", "두고 내렸어요"])
        return f"{co} {it} {verb} {st}에서요 {ex}".strip()
    return rng.choice(COMMANDS)


def owner_case(svc, rng: random.Random):
    """진짜 주인 역할: 보관함 물건 하나를 골라 그 물건의 실제 특징으로 신고하고, 확인 질문에는 정답을 준비한다.
    (메시지, 정답표 {칸: 답}, 물건 번호) 또는 None"""
    from agents.sim_world import MACHINE_STATION
    w = svc.world
    with w._lock:
        rows = [dict(r) for r in w.items.values() if r["loc"] == "bin" and r["status"] == "본센터 보관"]
    if not rows:
        return None
    r = rng.choice(rows)
    feats = {**r["features"], **r["private_features"]}
    station = MACHINE_STATION.get(r["machine_id"])
    say_station = station and rng.random() < 0.5
    color = feats.get("color") if feats.get("color") not in (None, "확인 불가", "기타") else ""
    msg = f"{color} {r['category']} 잃어버렸어요" + (f" {station}역에서요" if say_station else "")
    answers = {"place": f"{station}역" if station else "모름", "color": color or "모름",
               "visible_text": feats.get("visible_text", "모름"), "mark": feats.get("mark", "모름")}
    return msg.strip(), answers, r["item_id"]


def check(svc, ctx: dict) -> list[str]:
    """규칙 위반 목록(빈 목록이면 정상)."""
    v = []
    w = svc.world
    with w._lock:
        items = {k: dict(r) for k, r in w.items.items()}
        arm = dict(w.arm)
    slots = [r["slot"] for r in items.values() if r["loc"] == "bin"]
    if None in slots or len(slots) != len(set(slots)):
        v.append(f"보관함 칸 중복/빈 칸 번호: {slots}")
    in_grip = [k for k, r in items.items() if r["loc"] == "gripper"]
    if len(in_grip) > 1 or (in_grip and arm.get("holding") != in_grip[0]) or (arm.get("holding") and not in_grip):
        v.append(f"집게 상태 불일치: 들고 있음={arm.get('holding')} · 위치={in_grip}")
    for k, r in items.items():
        ok = LOC_OK.get(r["status"])
        if ok is not None and r["loc"] not in ok:
            v.append(f"{k} 상태 {r['status']} 인데 위치 {r['loc']}")
    for m in svc.reporter.messages:
        if find_pii(f"{m['title']}\n{m['body']}"):
            v.append(f"관제 메시지에 개인정보 모양: {m['channel']}")
    for k, r in items.items():
        if find_pii(r.get("place_text") or ""):
            v.append(f"{k} 장소 글에 개인정보 모양이 저장됨")
    # 반환된 물건은 찾기 요청의 물건과 같아야 한다(엉뚱한 물건 반환 금지)
    for st in svc.board.stories.values():
        res, ids = st.get("result"), st.get("ids", {})
        if res and any(s["state"] == "active" for s in st["stages"]):    # 끝난 이야기에 '진행 중' 단계가 남으면 안 됨
            v.append(f"{st['story_id']} 끝났는데 진행 중 단계가 남음")
        if st["kind"] == "lost" and res and res["ok"] and ids.get("item_id"):
            got = items.get(ids["item_id"])
            if got is None:            # 초기화로 세계에서 지워진 물건(번호는 다시 쓰지 않음)
                continue
            if got["loc"] not in ("handed", "basket"):
                v.append(f"{st['story_id']} 성공인데 물건 {ids['item_id']} 위치 {got and got['loc']}")
    for cid, row in getattr(svc.claims, "_rows", {}).items():   # 찾기 요청 저장값에 개인정보가 섞이면 안 됨
        if any(find_pii(str(v)) for v in (row.get("description") or {}).values()):
            v.append(f"{cid} 찾기 요청 설명에 개인정보 모양이 저장됨")
    basket = [k for k, r in items.items() if r["loc"] == "basket"]
    for k in basket:
        if items[k]["status"] not in (HANDOVER_WAIT, "반환 중", HANDOVER_HOLD):
            v.append(f"바구니의 {k} 상태가 {items[k]['status']}")
    if len(svc.board.stories) < ctx.get("stories", 0):
        v.append("이야기 기록이 사라짐")
    return v


def run(runs: int, seed: int, timed: int = 0, verbose: bool = False) -> dict:
    rng = random.Random(seed)
    svc = build_sim_service({"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"})
    bot = BotCore(InProcClient(svc))
    stats, problems, replies, reasons = Counter(), [], Counter(), Counter()
    seen_stories = 0
    t0 = time.time()
    for i in range(1, runs + timed + 1):
        timed_run = i > runs
        svc.world.speed = 0.02 if timed_run else 0.0
        author = f"u{rng.randint(1, 3)}"
        owner = owner_case(svc, rng) if rng.random() < 0.3 else None
        msg = owner[0] if owner else rand_message(rng)
        kind = "owner" if owner else classify(msg)
        stopper = None
        if timed_run and kind == "lost":       # 반환 도중 무작위 시각에 정지 버튼
            delay = rng.uniform(0.02, 0.6)
            stopper = threading.Timer(delay, lambda: bot.handle("staff", "정지"))
            stopper.start()
        try:
            reply, story = bot.handle(author, msg)
        except Exception as e:                  # 봇 핵심이 예외를 밖으로 내면 안 됨
            problems.append((i, kind, f"봇 예외 {type(e).__name__}: {e}"))
            continue
        if not reply and msg.strip():
            problems.append((i, kind, "빈 답"))
        if len(reply) > 2000:
            problems.append((i, kind, f"답이 디스코드 한도 초과({len(reply)}자)"))
        replies[reply.split("\n")[0][:18]] += 1
        for _ in range(4):                             # 질문이 이어지면(색 → 역 등) 남은 질문에 계속 답한다
            if author not in bot.pending:
                break
            if owner:                                  # 진짜 주인은 질문한 칸의 정답을 말한다
                field = svc.sim.pending.get(bot.pending[author][0], {}).get("field")
                reply2, story = bot.handle(author, owner[1].get(field, "모름"))
                stats["주인 정답"] += 1
            elif rng.random() < 0.8:                   # 그 밖에는 무작위 답(일부는 답하지 않고 다음 메시지로)
                reply2, story = bot.handle(author, rng.choice(ANSWERS) or "모름")
                stats["확인 질문 답"] += 1
            else:
                break
        if not svc.sim.wait_idle(60):
            problems.append((i, kind, "이야기가 60초 안에 끝나지 않음"))
        if stopper:
            stopper.join()
            svc.sim.wait_idle(60)
        if story:
            st = svc.board.story(story)
            if not st or not st.get("result"):
                problems.append((i, kind, f"{story} 결과 없음"))
            else:
                stats[f"{st['kind']}:{'성공' if st['result']['ok'] else '중단'}"] += 1
                reasons[re.sub(r"[A-Z]-\d{8}-\d{4}", "#", st["result"]["text"])[:70]] += 1
                if owner and not st["result"]["ok"] and "rejected" in st["result"]["text"] and not stopper:
                    oi = svc.world.items.get(owner[2], {})
                    pi = svc.world.items.get(st["ids"].get("item_id"), {})
                    brief = lambda r: f"{r.get('item_id')}({r.get('machine_id')},{r.get('features', {}).get('color')},{r.get('private_features', {}).get('visible_text')})"  # noqa: E731
                    problems.append((i, kind, f"진짜 주인인데 반환 거절: 주인 {brief(oi)} / 고른 후보 {brief(pi)} / 메시지 '{owner[0]}'"))
                if owner and st["result"]["ok"] and st["ids"].get("item_id") != owner[2]:
                    problems.append((i, kind, "진짜 주인에게 다른 물건을 돌려줌"))
                txt = progress_text(st)
                if len(txt) > 2000:
                    problems.append((i, kind, "진행판 글이 너무 김"))
        if svc.world.arm["stopped"]:                       # 정지가 남아 있으면 직원처럼 원점 복귀
            svc.world.speed = 0.0
            bot.handle("staff", "원점")
            stats["정지 → 원점 복귀"] += 1
            if svc.world.arm["stopped"]:
                problems.append((i, kind, "원점 복귀 뒤에도 정지 상태"))
        for p in check(svc, {"stories": seen_stories}):
            problems.append((i, kind, p))
        stats[kind] += 1
        seen_stories = len(svc.board.stories)
        free = svc.world.free_slot()
        if free is None and rng.random() < 0.5:          # 보관함이 꽉 차면 가끔 초기화
            bot.handle("staff", "초기화")
            stats["꽉 차서 초기화"] += 1
        if verbose:
            print(i, kind, reply.split("\n")[0][:60])
    uniq = []
    for p in problems:
        if p[2] not in [u[2] for u in uniq]:
            uniq.append(p)
    return {"runs": runs + timed, "seconds": round(time.time() - t0, 1), "stats": dict(stats),
            "problems": len(problems), "unique": uniq, "replies": dict(replies.most_common(12)),
            "reasons": reasons.most_common(15)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="가상 시연 무작위 시험")
    ap.add_argument("--runs", type=int, default=120)
    ap.add_argument("--timed", type=int, default=0, help="시간 지연을 켠 회차 수(정지 버튼 시험)")
    ap.add_argument("--seed", type=int, default=1104)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    r = run(a.runs, a.seed, a.timed, a.verbose)
    print(f"무작위 시험 {r['runs']}회 · {r['seconds']}초 · seed {a.seed}")
    print("결과:", ", ".join(f"{k} {v}" for k, v in sorted(r["stats"].items())))
    print("이야기 결과별:")
    for text, n in r["reasons"]:
        print(f"  {n:>4} {text}")
    print(f"위반 {r['problems']}건 (종류 {len(r['unique'])}가지)")
    for i, kind, p in r["unique"]:
        print(f"  - {i}회차({kind}): {p}")
    return 1 if r["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
