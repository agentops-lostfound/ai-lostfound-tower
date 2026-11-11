"""화면이 부르는 API 전체를 무작위로 섞는 가상 시연 시험 — 11/9~11/10 기능까지 (LF-18, 11/10 변재원)

한줄 설명: 키오스크 사진 접수·사진 분석 결과·분실 신고·확인 질문·챗봇 대화 접수·대화로 취소·본센터 키오스크 회수·
직원 확인 후 진행·찾기 요청 취소·제출보관함 교차 검증·인계·보류·원래 칸으로 되돌림·물건 카드 단추(회수·접수 취소·기록 삭제)·
정지/원점·보관 칸 직접 배정을 **화면과 같은 HTTP 주소로** 무작위로 누르고, 매번 규칙을 검사한다.

검사하는 규칙(위반이면 회차·주소·내용을 남김, 개인정보는 찍지 않음)
- 서버 오류(5xx)가 나지 않는다. 화면 상태 주소(/api/admin/live/state?detail=1)는 늘 200
- tools/sim_fuzz.py 의 세계 규칙(칸 중복·집게·상태별 위치·바구니·성공한 반환은 그 물건) 그대로
- 취소된 찾기 요청으로 반환이 시작되지 않는다. 한 물건이 두 번 '인계 완료'되지 않는다
- 화면 상태와 관제 메시지에 전화번호·주민번호 모양이 없다(가린 값만)
- '인계 완료' 물건은 보관함 칸에 남지 않는다

사용법 (저장소 폴더, .venv 켠 상태 — 관제탑을 켜지 않아도 됨)
    python tools/sim_fuzz_api.py --runs 2000 --seed 1
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import sys
import time
from collections import Counter

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import HANDOVER_DONE  # noqa: E402
from discord_ops.reporter import find_pii  # noqa: E402
from tools.sim_fuzz import check as world_check  # noqa: E402

JPG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + bytes(64) + b"\xff\xd9").decode()
MACHINES = ["KIOSK-A", "KIOSK-C", "CENTER", "KIOSK-Z", ""]
PLACES = ["승강장", "5번 출구 앞", "개찰구 옆", "화장실 앞", "", "010-1234-5678 앞", "a" * 200]
QWEN_CATS = ["wallet", "card_wallet", "phone", "hand_cream", "power_bank", "usb", "lip_balm", "umbrella", ""]
QWEN_COLORS = [["black"], ["pink"], ["white"], ["green"], ["brown"], ["blue"], [], ["rainbow"]]
LOST_TEXTS = ["{st}에서 {c} {i} 잃어버렸어요", "{c} {i} 찾아요", "{i} 두고 내렸어요 {st}", "어제 {st} {c} {i} 분실", "{i}"]
STATIONS = ["중앙역", "초량역", "부산역", "센텀역", "", "모름"]
COLORS = ["분홍", "초록", "검정", "흰색", "갈색", "파랑", ""]
ITEMS = ["핸드크림", "카드지갑", "지갑", "휴대폰", "보조배터리", "우산", "립밤"]
CHAT = ["분실 접수하고 싶어요", "주운 물건 신고하고 싶어요", "분홍 핸드크림 잃어버렸어요 접수해 주세요", "모름", "어제", "없어요", "네",
        "고칠게요", "취소", "중앙", "초량", "부산역", "핸드크림", "카드지갑", "흰색", "분홍", "예약 취소는 어떻게 해요?",
        "찾기 요청 취소하고 싶어요", "아니요", "본센터 몇 시에 열어요?", "초록 핸드크림 있어요?", "", "ㅋㅋ", "010-9999-8888"]
IDENT = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-1******"}
BAD_IDENT = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-2******"}
ID_OK = "******-1******"
PII = re.compile(r"01[016789]-?\d{3,4}-?\d{4}|\d{6}-?[1-4]\d{6}")


class Runner:
    def __init__(self, seed: int, seed_set: str = "one"):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        env = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_AGENT_TALK": "1"}
        if seed_set == "full":
            env["TOWER_SIM_SEED"] = "full"
        self.svc = build_sim_service(env)
        self.c = TestClient(build_app(self.svc), raise_server_exceptions=False)
        self.rng = random.Random(seed)
        self.claims, self.items, self.cases, self.chat_sids = [], [], [], []
        self.cancelled: set[str] = set()
        self.done_count: Counter = Counter()
        self.v: list[str] = []
        self.calls: Counter = Counter()
        self.codes: Counter = Counter()

    # ---------- 부르기 ----------
    def call(self, method: str, path: str, body=None, tag: str | None = None):
        tag = tag or path
        self.calls[tag] += 1
        r = self.c.request(method, path, json=body) if body is not None else self.c.request(method, path)
        self.codes[(tag, r.status_code)] += 1
        if r.status_code >= 500:
            self.v.append(f"서버 오류 {r.status_code}: {method} {tag} — {r.text[:160]}")
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None

    def pick(self, xs):
        return self.rng.choice(xs) if xs else None

    def idle(self):
        self.svc.sim.wait_idle(5)

    # ---------- 동작 ----------
    def kiosk_intake(self):
        body = {"machine_id": self.pick(MACHINES), "place_text": self.pick(PLACES)}
        if self.rng.random() < 0.9:
            body["photo"] = JPG
        if self.rng.random() < 0.3:
            body["finder"] = {"name": "김습득", "phone": "010-1234-5678"}
        code, d = self.call("POST", "/api/kiosk/items", body, "/api/kiosk/items")
        if code == 200 and d and d.get("item_id"):
            self.items.append(d["item_id"])
            if self.rng.random() < 0.85:
                q = {"category": self.pick(QWEN_CATS), "colors": self.pick(QWEN_COLORS), "shape": "tube", "material": "plastic"}
                if self.rng.random() < 0.3:
                    q["visible_text"] = self.pick(["VOVA", "ATRIX", "010-2222-3333", ""])
                self.call("POST", f"/api/kiosk/items/{d['item_id']}/features", {"qwen": q, "confidence": self.rng.random()},
                          "/api/kiosk/items/{id}/features")
            self.idle()

    def found_text(self):
        t = f"{self.pick(STATIONS)} {self.pick(['5번 출구', '승강장', ''])}에서 {self.pick(COLORS)} {self.pick(ITEMS)} 주웠어요"
        code, d = self.call("POST", "/sim/found", {"text": t}, "/sim/found")
        if code == 200 and d and d.get("item_id"):
            self.items.append(d["item_id"])
        self.idle()

    def lost(self):
        t = self.pick(LOST_TEXTS).format(st=self.pick(STATIONS), c=self.pick(COLORS), i=self.pick(ITEMS))
        body = {"text": t, "visit": self.pick(["kiosk", "kiosk", "staff"]), "name_masked": "홍*동", "id_no_masked": ID_OK}
        if self.rng.random() < 0.2:
            body["place_unknown"] = True
        code, d = self.call("POST", "/sim/lost", body, "/sim/lost")
        for _ in range(4):
            if not (code == 200 and d and d.get("pending_id")):
                break
            code, d = self.call("POST", f"/sim/lost/{d['pending_id']}/answer", {"text": self.pick(["모름", "중앙", "분홍", "초록", "초량", ""])},
                                "/sim/lost/{id}/answer")
        if code == 200 and d and d.get("claim_id"):
            self.claims.append(d["claim_id"])
        self.idle()

    def kiosk_return(self):
        cid = self.pick(self.claims) if self.rng.random() < 0.9 else "C-20991231-0001"
        if not cid:
            return
        idno = ID_OK if self.rng.random() < 0.8 else "******-2******"
        code, d = self.call("POST", "/api/kiosk/returns", {"machine_id": self.pick(["CENTER", "CENTER", "KIOSK-A"]), "claim_id": cid,
                                                            "id_no_masked": idno}, "/api/kiosk/returns")
        self.after_return(cid, code, d)

    def after_return(self, cid, code, d):
        if code == 200 and d and d.get("case_id"):
            if cid in self.cancelled:
                self.v.append(f"취소된 찾기 요청 {cid} 으로 반환이 시작됨({d.get('decision')})")
            self.cases.append(d["case_id"])
        self.idle()

    def staff_visit(self):
        cid = self.pick(self.claims)
        if cid:
            code, d = self.call("POST", f"/api/admin/claims/{cid}/visit", {}, "/api/admin/claims/{id}/visit")
            self.after_return(cid, code, d)

    def staff_return(self):
        cid = self.pick(self.claims)
        if not cid:
            return
        body = {"claim_id": cid, "visitor_id_match": self.rng.random() < 0.8, "inner_feature_ok": self.rng.random() < 0.8,
                "staff_confirmed": self.rng.random() < 0.8}
        if self.rng.random() < 0.3:
            body["staff_quiz_override"] = True
        code, d = self.call("POST", "/api/admin/returns", body, "/api/admin/returns")
        self.after_return(cid, code, d)

    def cancel(self):
        cid = self.pick(self.claims)
        if not cid:
            return
        if self.rng.random() < 0.5:
            code, _ = self.call("POST", f"/api/admin/claims/{cid}/cancel", {}, "/api/admin/claims/{id}/cancel")
        else:
            code, _ = self.call("POST", f"/api/lost/claims/{cid}/cancel", {"id_no_masked": self.pick([ID_OK, ID_OK, "******-3******", ""])},
                                "/api/lost/claims/{id}/cancel")
        if code == 200:
            self.cancelled.add(cid)
        self.idle()

    def pickup(self):
        """11/11 무인 인계: 키오스크 [물건 받았어요]. 확인 질문을 못 넘은(직원 대면 확인) 요청은 키오스크로 끝나면 안 된다"""
        cid = self.pick(self.claims)
        if not cid:
            return
        idno = ID_OK if self.rng.random() < 0.85 else "******-2******"
        code, d = self.call("POST", "/api/kiosk/handover", {"machine_id": self.pick(["CENTER", "CENTER", "CENTER", "KIOSK-A"]),
                                                             "claim_id": cid, "id_no_masked": idno}, "/api/kiosk/handover")
        if code == 200 and isinstance(d, dict):
            if idno != ID_OK:
                self.v.append(f"틀린 신분 번호로 {cid} 인계 완료됨")
            st = self.call("GET", f"/claims/{cid}", tag="/claims/{id}")[1]
            if isinstance(st, dict) and (st.get("web_gates") or {}).get("quiz_passed") is False:
                self.v.append(f"확인 질문 미통과 {cid} 가 키오스크로 인계 완료됨(직원 예외여야 함)")
            if d.get("item_id"):
                self.done_count[d["item_id"]] += 1
                if self.done_count[d["item_id"]] > 1:
                    self.v.append(f"물건 {d['item_id']} 가 두 번 인계 완료됨")
        self.idle()

    def handover(self):
        code, q = self.call("GET", "/api/admin/handovers?limit=50", tag="/api/admin/handovers")
        rows = q if isinstance(q, list) else []
        case = self.pick([r.get("case_id") for r in rows if isinstance(r, dict)]) or self.pick(self.cases)
        if not case:
            return
        roll = self.rng.random()
        if roll < 0.4:
            self.call("GET", f"/api/admin/returns/{case}/secret", tag="/api/admin/returns/{id}/secret")
            ok = self.rng.random() < 0.75
            code, d = self.call("POST", f"/api/admin/returns/{case}/verify",
                                {"item_match": ok, "id_match": ok or self.rng.random() < 0.5, "feature_match": True}, "/api/admin/returns/{id}/verify")
        elif roll < 0.7:
            code, d = self.call("POST", f"/api/admin/returns/{case}/handover", {"staff_confirmed": self.rng.random() < 0.9},
                                "/api/admin/returns/{id}/handover")
        elif roll < 0.85:
            code, d = self.call("POST", f"/api/admin/returns/{case}/hold", {"reason": self.pick(["본인 아님", "물건 다름", ""])},
                                "/api/admin/returns/{id}/hold")
        else:
            code, d = self.call("POST", f"/api/admin/returns/{case}/restock", {"staff_confirmed": True}, "/api/admin/returns/{id}/restock")
        if code == 200 and isinstance(d, dict) and d.get("status") == HANDOVER_DONE and d.get("item_id"):
            self.done_count[d["item_id"]] += 1
            if self.done_count[d["item_id"]] > 1:
                self.v.append(f"물건 {d['item_id']} 가 두 번 인계 완료됨")
        self.idle()

    def item_button(self):
        iid = self.pick(self.items) or self.pick(list(self.svc.world.items))
        if not iid:
            return
        act = self.pick(["collect", "cancel", "purge", "collect"])
        code, _ = self.call("POST", f"/api/admin/items/{iid}/{act}", {}, f"/api/admin/items/{{id}}/{act}")
        if act == "purge" and code == 200 and iid in self.items:
            self.items.remove(iid)
        self.idle()

    def robot(self):
        if self.rng.random() < 0.5:
            self.call("POST", "/api/robot/stop", {}, "/api/robot/stop")
        else:
            self.call("POST", "/api/admin/robot/home", {"staff_confirmed": True}, "/api/admin/robot/home")

    def storage(self):
        code, lay = self.call("GET", "/api/admin/storage", tag="/api/admin/storage")
        if self.rng.random() < 0.5 or not isinstance(lay, dict):
            return
        slots = [s["slot_id"] for sec in lay.get("sections", []) for s in sec.get("slots", [])]
        iid = self.pick(self.items)
        if iid and slots:
            self.call("POST", "/api/admin/storage/assign", {"item_id": iid, "slot_id": self.pick(slots)}, "/api/admin/storage/assign")

    def chat(self):
        if not self.chat_sids or self.rng.random() < 0.25:
            self.chat_sids.append(f"fz-{self.rng.randrange(10**8):08d}")
        sid = self.pick(self.chat_sids)
        body = {"question": self.pick(CHAT), "session_id": sid}
        r = self.rng.random()
        if r < 0.15:
            body["intake_action"] = self.pick([IDENT, IDENT, BAD_IDENT])
            body["question"] = body["question"] or "본인 확인"
        elif r < 0.3 and self.claims:
            body["question"] = f"{self.pick(self.claims)} 취소해 주세요"
        if not body["question"]:
            body["question"] = "안녕"
        code, d = self.call("POST", "/chat/questions", body, "/chat/questions")
        if code == 200 and isinstance(d, dict):
            info = d.get("intake") or {}
            if info.get("claim_id"):
                if info.get("kind") == "cancel" and d.get("status") == "intake_done":
                    self.cancelled.add(info["claim_id"])
                elif info.get("claim_id") not in self.claims:
                    self.claims.append(info["claim_id"])
            if PII.search(d.get("answer") or ""):
                self.v.append(f"챗봇 답에 개인정보 모양: {body['question'][:20]}")
        self.idle()

    def reset(self):
        self.call("POST", "/sim/reset", {}, "/sim/reset")
        self.claims, self.items, self.cases = [], [], []
        self.cancelled.clear()
        self.done_count.clear()
        self.idle()

    ACTIONS = (("kiosk_intake", 14), ("found_text", 8), ("lost", 14), ("kiosk_return", 10), ("staff_visit", 5), ("staff_return", 4),
               ("cancel", 5), ("pickup", 10), ("handover", 8), ("item_button", 4), ("robot", 2), ("storage", 3), ("chat", 16), ("reset", 0.4))

    # ---------- 검사 ----------
    def check(self, i: int, name: str) -> None:
        before = len(self.v)
        code, st = self.call("GET", "/api/admin/live/state?detail=1", tag="/api/admin/live/state")
        if code != 200:
            self.v.append(f"화면 상태 주소 {code}")
        else:
            text = json.dumps(st, ensure_ascii=False)
            if PII.search(text):
                self.v.append(f"화면 상태에 개인정보 모양: {PII.search(text).group(0)[:4]}…")
        for msg in world_check(self.svc, {"stories": 0}):
            self.v.append(msg)
        lay = self.svc.storage.layout()
        for sec in lay["sections"]:
            for sl in sec["slots"]:
                it = sl.get("item")
                if it and it.get("status") == HANDOVER_DONE:
                    self.v.append(f"인계 완료 물건 {it['item_id']} 가 칸 {sl['slot_id']} 에 남음")
        if len(self.v) > before:
            self.v[before:] = [f"[{i}:{name}] {x}" for x in self.v[before:]]


def run(runs: int, seed: int, seed_set: str = "one") -> dict:
    r = Runner(seed, seed_set)
    names = [a for a, _ in Runner.ACTIONS]
    weights = [w for _, w in Runner.ACTIONS]
    t0 = time.time()
    for i in range(1, runs + 1):
        name = r.rng.choices(names, weights)[0]
        try:
            getattr(r, name)()
        except Exception as e:                       # 시험기 자체 오류도 남긴다(관제탑 쪽 예외가 새어 나온 것일 수 있음)
            r.v.append(f"[{i}:{name}] 예외 {type(e).__name__}: {str(e)[:120]}")
        r.check(i, name)
    uniq = Counter(re.sub(r"[A-Z]-\d{8}-\d{4}|R-C-\d{8}-\d{4}(-\d+)?|C-\d{8}-\d{4}|\[\d+:", "#", x) for x in r.v)
    return {"runs": runs, "seconds": round(time.time() - t0, 1), "violations": r.v, "kinds": uniq, "calls": r.calls, "codes": r.codes,
            "stories": len(r.svc.board.stories)}


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="화면 API 전체 무작위 시험")
    ap.add_argument("--runs", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1110)
    ap.add_argument("--seed-set", choices=("one", "full"), default="one")
    ap.add_argument("--codes", action="store_true", help="주소별 응답 코드 분포도 출력")
    a = ap.parse_args(argv)
    out = run(a.runs, a.seed, a.seed_set)
    print(f"동작 {out['runs']}개 · 이야기 {out['stories']}개 · {out['seconds']}초")
    if a.codes:
        for (tag, code), n in sorted(out["codes"].items()):
            print(f"  {code} {n:5d} {tag}")
    for k, n in out["kinds"].most_common(30):
        print(f"{n:5d} {k}")
    print(f"위반 {len(out['violations'])}건 (종류 {len(out['kinds'])}가지)")
    return 1 if out["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
