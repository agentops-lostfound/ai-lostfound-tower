"""챗봇 질문 500개 채점표 (LF-5 · 11/9 변재원)

한줄 설명: 질문 500개(기본 안내 → 검색 → 이어 묻기 → 챗봇이 직접 접수를 끝내는 여러 턴 대화 → 안전·직원 관제)를
챗봇 전체 경로에 넣고 문항마다 0/1 로 채점한 뒤, 실행할 때마다 엑셀에 '단계' 열을 하나씩 늘려 기록한다.

왜: 프롬프트·모델·에이전트 구조를 바꿀 때마다 "무엇이 좋아지고(0→1) 무엇이 나빠졌는지(1→0)"를 같은 질문으로 비교하려고.
Langfuse 무료 요금제는 지난 30일만 보이므로, 결과의 원본은 저장소(evaluation/runs/*.json)에 영구 보관한다.

사용법 (저장소 폴더, .venv 켠 상태 — 관제탑을 켜지 않아도 된다: 매 문항마다 새 가상 관제탑을 메모리에 만든다)
    python evaluation/chat_eval.py                          # 500개 전체, .env 의 모델(LF_CHAT_RAG_MODEL), Langfuse 기록 끔
    python evaluation/chat_eval.py --rules                  # 모델 없이 규칙만(빠름, 구조 확인용)
    python evaluation/chat_eval.py --only 1-50,201          # 일부 문항만(엑셀에는 기록하지 않음, --record 로 기록)
    python evaluation/chat_eval.py --group 임무             # 분류 이름에 '임무'가 들어간 문항만
    python evaluation/chat_eval.py --trace --lf             # Langfuse 로 보낼 고정 50문항만, 기록 켬(월 한도 아끼기)
    python evaluation/chat_eval.py --note "planner 프롬프트 v3"   # 단계 정보 시트에 메모
    python evaluation/chat_eval.py --excel-only             # 실행 없이 기존 기록으로 엑셀만 다시 만듦
결과
- evaluation/runs/<단계>.json      문항별 0/1·실패 이유·답 일부·걸린 시간 + 단계 정보(커밋·모델·프롬프트 버전)
- evaluation/chat_eval_scores.xlsx  점수(단계 열 누적, 0→1 초록·1→0 빨강) · 분류별 · 단계 정보 · 실패 이유 · 사람 판정
- 사람 판정: 엑셀 '사람 판정' 시트에 (단계, 번호, 점수, 이유)를 적고 저장하면 다음 실행 때 evaluation/chat_eval_overrides.csv 로
  옮겨지고 자동 채점보다 우선한다(자동 채점이 틀린 경우 바로잡기)
문항 형식(evaluation/chat_eval_500.json): {no, group, level, title, lf?, turns: [{say | action, staff?, expect?}]}
  expect: any(하나라도) · all(모두) · not(없어야) · status · gen · gen_not · path_has · path_not · choices_any · cand[min,max] · id(정규식) · http
  여러 턴이면 모든 턴이 통과해야 1점. expect 가 없는 턴은 공통 검사만 한다
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EVAL = ROOT / "evaluation"
QUESTIONS = EVAL / "chat_eval_500.json"
RUNS = EVAL / "runs"
XLSX = EVAL / "chat_eval_scores.xlsx"
OVERRIDES = EVAL / "chat_eval_overrides.csv"

ID_MASKED = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-1******"}
ID_RAW = {"type": "identity", "name_masked": "홍길동", "id_no_masked": "900101-1234567"}
BROKEN = re.compile(r"[있없]요|[가-힣]{2,}요요")
TOPIC_NAME = re.compile(r"\b[a-z]+_[a-z_]+\b")
RAW_ID = re.compile(r"\d{6}\s*-\s*[1-4]\d{6}")
RAW_PHONE = re.compile(r"01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}")
# 11/10: 평소 가상 시연은 분홍 핸드크림 하나로 시작하지만, 채점 문항(갈색 카드지갑·파란 휴대폰·흰 보조배터리 …)은 예전 5개 묶음을 기준으로 쓰였다
SIM_ENV = {"TOWER_SIM": "1", "TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SEND": "0", "TOWER_AGENT_TALK": "0"}


# ---------------------------------------------------------------- 채점

def check_turn(turn: dict, code: int, res: dict) -> list[str]:
    """한 턴의 실패 이유(비면 통과). 공통 검사 + 문항의 expect"""
    exp = turn.get("expect") or {}
    want_http = exp.get("http", 200)
    if code != want_http:
        return [f"HTTP {code} (기대 {want_http})"]
    if code != 200:
        return []
    answer = res.get("answer") or ""
    choices = [str(c) for c in res.get("choices") or []]
    shown = answer + " " + " ".join(choices)
    path = res.get("agent_path") or []
    why = []
    if not answer.strip() and res.get("status") != "intake_none":
        why.append("빈 답")
    if BROKEN.search(shown):
        why.append("깨진 낱말 끝: " + BROKEN.search(shown).group(0))
    if TOPIC_NAME.search(shown):
        why.append("영어 주제 이름: " + TOPIC_NAME.search(shown).group(0))
    if RAW_ID.search(shown) or RAW_PHONE.search(shown):
        why.append("답에 주민번호·전화번호 원문")
    if len(answer) > 1500:
        why.append(f"답이 너무 김({len(answer)}자)")
    if exp.get("any") and not any(w in shown for w in exp["any"]):
        why.append("꼭 있어야 할 말(하나라도) 없음: " + "/".join(exp["any"]))
    for w in exp.get("all", []):
        if w not in shown:
            why.append(f"꼭 있어야 할 말 없음: {w}")
    for w in exp.get("not", []):
        if w in shown:
            why.append(f"나오면 안 되는 말: {w}")
    if exp.get("status") and res.get("status") not in exp["status"]:
        why.append(f"상태 {res.get('status')} (기대 {'/'.join(exp['status'])})")
    if exp.get("gen") and res.get("generation_status") not in exp["gen"]:
        why.append(f"생성 상태 {res.get('generation_status')} (기대 {'/'.join(map(str, exp['gen']))})")
    if res.get("generation_status") in exp.get("gen_not", []):
        why.append(f"나오면 안 되는 생성 상태: {res.get('generation_status')}")
    for a in exp.get("path_has", []):
        if a not in path:
            why.append(f"거쳐야 할 에이전트 없음: {a}")
    for a in exp.get("path_not", []):
        if a in path:
            why.append(f"거치면 안 되는 에이전트: {a}")
    if exp.get("choices_any") and not any(c in choices for c in exp["choices_any"]):
        why.append("버튼 없음: " + "/".join(exp["choices_any"]))
    if "cand" in exp:
        n, (lo, hi) = len(res.get("candidates") or []), exp["cand"]
        if n < lo or (hi is not None and n > hi):
            why.append(f"후보 {n}개 (기대 {lo}~{'' if hi is None else hi})")
    if exp.get("id") and not re.search(exp["id"], shown):
        why.append(f"번호 없음: {exp['id']}")
    return why


class Runner:
    """문항 하나 = 새 가상 관제탑 하나(앞 문항의 접수가 다음 문항 검색에 섞이지 않게)"""

    def __init__(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        self._TestClient, self._build_app, self._build_sim = TestClient, build_app, build_sim_service

    def fresh(self):
        svc = self._build_sim(dict(SIM_ENV))
        return svc, self._TestClient(self._build_app(service=svc))

    def run_item(self, item: dict) -> dict:
        svc, client = self.fresh()
        sid = f"eval-{item['no']:04d}-{int(time.time() * 1000) % 100000:05d}"
        histories, turns, t0, wait_id = {}, [], time.perf_counter(), ""
        confirmations = {}
        for k, turn in enumerate(item["turns"]):
            if turn.get("wait"):                                   # 가상 세계의 뒤 작업(자동 연결 등)이 끝나길 기다림
                try:
                    svc.sim.wait_idle(60)
                except Exception:
                    pass
            say = turn.get("say") or "본인 확인 정보를 입력했어요"
            if turn.get("fill_wait"):                              # 앞 턴에서 받은 대기 번호를 넣어 조회
                say = say.replace("L-{wait}", wait_id or "L-00000000-0000")
            history = histories.setdefault(turn.get("session") or "", [])     # 다른 사람(session)은 대화 기록을 따로
            body = {"question": say, "history": history[-4:],
                    "session_id": turn.get("session") and f"{sid}-{turn['session']}" or sid}
            if turn.get("staff"):
                body["mode"] = "staff"
            if turn.get("mode"):
                body["mode"] = turn["mode"]
            if turn.get("action") == "identity":
                body["intake_action"] = ID_MASKED
            elif turn.get("action") == "identity_raw":
                body["intake_action"] = ID_RAW
            elif re.fullmatch(r'접수할게요|네|예|응|좋아요|맞아요|확인|접수|그래요?|ㅇㅇ|넵', body['question'].strip()):
                if body['session_id'] in confirmations and not turn.get('omit_confirmation'):
                    body['intake_action'] = dict(confirmations[body['session_id']])
            ts = time.perf_counter()
            try:
                r = client.post("/chat/questions", json=body)
                code, res = r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})
                if isinstance(res, dict) and res.get('confirmation'):
                    confirmations[body['session_id']] = dict(res['confirmation'])
                elif isinstance(res, dict) and res.get('status') != 'intake_done':
                    confirmations.pop(body['session_id'], None)
            except Exception as e:                                   # 한 문항이 예외여도 나머지는 돈다
                code, res = 599, {"answer": "", "generation_status": f"예외 {type(e).__name__}: {str(e)[:120]}"}
            why = check_turn(turn, code, res if isinstance(res, dict) else {})
            answer = (res.get("answer") or "") if isinstance(res, dict) else ""
            m = re.search(r"L-\d{8}-\d{4}", answer)
            if m and not turn.get("fill_wait"):
                wait_id = m.group(0)
            turns.append({"say": body["question"], "ok": not why, "why": why, "seconds": round(time.perf_counter() - ts, 2),
                          "status": res.get("status") if isinstance(res, dict) else None,
                          "gen": res.get("generation_status") if isinstance(res, dict) else None,
                          "path": res.get("agent_path") if isinstance(res, dict) else None,
                          "answer": answer[:400], "choices": (res.get("choices") or []) if isinstance(res, dict) else []})
            if code == 200 and not turn.get("no_history"):
                history.append({"q": body["question"], "a": answer[:300]})
        try:
            svc.sim.wait_idle(5)
        except Exception:
            pass
        ok = all(t["ok"] for t in turns)
        return {"no": item["no"], "score": int(ok), "seconds": round(time.perf_counter() - t0, 2),
                "why": [f"{i + 1}턴: {w}" for i, t in enumerate(turns) for w in t["why"]], "turns": turns}


# ---------------------------------------------------------------- 단계 정보

def git_commit() -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %s"], capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True,
                               timeout=10).stdout.strip()
        return out.stdout.strip()[:80] + (" (+고친 파일 있음)" if dirty else "")
    except Exception:
        return "TBD"


def model_info(rules: bool) -> dict:
    """어떤 모델·프롬프트로 돌렸는지(비밀값은 이름만 보고 값은 안 씀)"""
    if rules:
        return {"model": "규칙만(--rules)"}
    info = {k: os.environ[k] for k in ('LF_CHAT_RAG_MODEL', 'LF_CHAT_AGENT_MODEL', 'LF_CHAT_MODEL', 'OPS_ANALYST_MODEL')
            if os.environ.get(k)}
    try:
        from agents import prompts
        vers = getattr(prompts, "loaded_versions", None)
        if callable(vers):
            info["prompts"] = vers()
            info['prompt_provenance'] = prompts.usage_summary()
    except Exception:
        pass
    return info or {"model": "TBD"}


def next_step_name(existing: list[str], now: dt.datetime) -> str:
    day = f"{now.month}/{now.day}"
    n = sum(1 for s in existing if s.split(" ")[0] == day)
    return f"{day} {n + 1:02d}"


def load_runs() -> list[dict]:
    runs = []
    for p in sorted(RUNS.glob("*.json")):
        try:
            runs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(runs, key=lambda r: r["meta"]["started"])


# ---------------------------------------------------------------- 사람 판정

def load_overrides() -> dict:
    out = {}
    if OVERRIDES.exists():
        with OVERRIDES.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    out[(row["단계"].strip(), int(row["번호"]))] = (int(row["점수"]), row.get("이유", ""))
                except (KeyError, ValueError):
                    continue
    return out


def pull_overrides_from_excel() -> int:
    """엑셀 '사람 판정' 시트에 사람이 적은 줄을 overrides.csv 로 옮김(엑셀은 매번 새로 만들어지므로)"""
    if not XLSX.exists():
        return 0
    try:
        import openpyxl
        ws = openpyxl.load_workbook(XLSX, data_only=True)["사람 판정"]
    except Exception:
        return 0
    have = load_overrides()
    added = 0
    for row in ws.iter_rows(min_row=2, values_only=True):
        step, no, score, why = (list(row) + [None] * 4)[:4]
        if step is None or no is None or score not in (0, 1, "0", "1"):
            continue
        key = (str(step).strip(), int(no))
        if have.get(key, (None,))[0] != int(score):
            have[key] = (int(score), str(why or ""))
            added += 1
    with OVERRIDES.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["단계", "번호", "점수", "이유"])
        for (s, n), (sc, why) in sorted(have.items(), key=lambda x: (x[0][0], x[0][1])):
            w.writerow([s, n, sc, why])
    return added


# ---------------------------------------------------------------- 엑셀

def build_excel(items: list[dict], runs: list[dict], path: Path = XLSX) -> None:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    ov = load_overrides()
    steps = [r["meta"]["step"] for r in runs]
    scores = []                                               # 단계별 {no: 점수}
    for r in runs:
        s = {x["no"]: x["score"] for x in r["results"]}
        for (st, no), (sc, _) in ov.items():
            if st == r["meta"]["step"] and no in s:
                s[no] = sc
        scores.append(s)
    green, red = PatternFill("solid", fgColor="DCF5E3"), PatternFill("solid", fgColor="FBE0E0")
    up, down = PatternFill("solid", fgColor="34C759"), PatternFill("solid", fgColor="FF453A")
    head = PatternFill("solid", fgColor="E8EEF8")
    bold = Font(bold=True)
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "점수"
    fixed = ["번호", "분류", "수준", "턴", "질문(첫 말)", "확인하는 것"]
    ws.append(fixed + steps)
    for c in ws[1]:
        c.font, c.fill = bold, head
    for it in items:
        row = [it["no"], it["group"], it["level"], len(it["turns"]), it["turns"][0].get("say") or "(양식)", it.get("title", "")]
        ws.append(row + [s.get(it["no"]) for s in scores])
    last = len(items) + 1
    for j, _ in enumerate(steps):
        col = len(fixed) + 1 + j
        letter = get_column_letter(col)
        for i in range(2, last + 1):
            c = ws.cell(row=i, column=col)
            if c.value is None:
                continue
            prev = ws.cell(row=i, column=col - 1).value if j > 0 else None
            if j > 0 and prev in (0, 1) and prev != c.value:
                c.fill, c.font = (up if c.value == 1 else down), Font(bold=True, color="FFFFFF")
            else:
                c.fill = green if c.value == 1 else red
            c.alignment = Alignment(horizontal="center")
        ws.cell(row=last + 1, column=col, value=f"=SUM({letter}2:{letter}{last})").font = bold
        ws.cell(row=last + 2, column=col, value=f'=IFERROR({letter}{last + 1}/COUNT({letter}2:{letter}{last}),0)').number_format = "0.0%"
    ws.cell(row=last + 1, column=5, value="합계(1의 개수)").font = bold
    ws.cell(row=last + 2, column=5, value="통과율").font = bold
    for col, width in zip("ABCDEF", (6, 16, 10, 5, 46, 40)):
        ws.column_dimensions[col].width = width
    for j in range(len(steps)):
        ws.column_dimensions[get_column_letter(len(fixed) + 1 + j)].width = 9
    ws.freeze_panes = ws.cell(row=2, column=len(fixed) + 1)

    wg = wb.create_sheet("분류별")
    groups = list(dict.fromkeys(it["group"] for it in items))
    wg.append(["분류", "문항 수"] + steps)
    for c in wg[1]:
        c.font, c.fill = bold, head
    for g in groups + ["전체"]:
        nos = [it["no"] for it in items if g == "전체" or it["group"] == g]
        wg.append([g, len(nos)] + [sum(s.get(n, 0) or 0 for n in nos) for s in scores])
    wg.column_dimensions["A"].width = 26

    wi = wb.create_sheet("단계 정보")
    wi.append(["단계", "시작", "걸린 시간(분)", "문항 수", "통과", "통과율", "0→1", "1→0", "git 커밋", "모델·프롬프트", "메모"])
    for c in wi[1]:
        c.font, c.fill = bold, head
    for k, r in enumerate(runs):
        s = scores[k]
        prev = scores[k - 1] if k else {}
        ups = sum(1 for n, v in s.items() if prev.get(n) == 0 and v == 1)
        downs = sum(1 for n, v in s.items() if prev.get(n) == 1 and v == 0)
        m = r["meta"]
        wi.append([m["step"], m["started"], round(m.get("seconds", 0) / 60, 1), len(s), sum(s.values()),
                   round(sum(s.values()) / max(len(s), 1), 3), ups, downs, m.get("commit", ""),
                   json.dumps(m.get("model", {}), ensure_ascii=False), m.get("note", "")])
    for col, width in zip("ABCDEFGHIJK", (9, 20, 12, 8, 8, 8, 6, 6, 40, 50, 30)):
        wi.column_dimensions[col].width = width

    wf = wb.create_sheet("실패 이유(최근)")
    wf.append(["번호", "분류", "질문(첫 말)", "실패 이유", "마지막 답(앞부분)"])
    for c in wf[1]:
        c.font, c.fill = bold, head
    if runs:
        by_no = {it["no"]: it for it in items}
        for x in runs[-1]["results"]:
            if x["score"] == 0 and x["no"] in by_no:
                it = by_no[x["no"]]
                wf.append([x["no"], it["group"], it["turns"][0].get("say") or "", " / ".join(x["why"])[:500],
                           (x["turns"][-1]["answer"] if x["turns"] else "")[:300]])
    for col, width in zip("ABCDE", (6, 16, 40, 60, 60)):
        wf.column_dimensions[col].width = width

    wh = wb.create_sheet("사람 판정")
    wh.append(["단계", "번호", "점수(0/1)", "이유"])
    for c in wh[1]:
        c.font, c.fill = bold, head
    for (st, no), (sc, why) in sorted(ov.items()):
        wh.append([st, no, sc, why])
    wh.column_dimensions["D"].width = 60
    wh.cell(row=1, column=6, value="자동 채점이 틀렸으면 여기에 (단계, 번호, 점수, 이유)를 적고 저장 → 다음 실행 때 반영")

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ---------------------------------------------------------------- 실행

def pick(items: list[dict], only: str, group: str, lf: bool) -> list[dict]:
    out = items
    if only:
        want = set()
        for part in only.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                want.update(range(int(a), int(b) + 1))
            elif part:
                want.add(int(part))
        out = [it for it in out if it["no"] in want]
    if group:
        out = [it for it in out if group in it["group"] or group in it["level"]]
    if lf:
        out = [it for it in out if it.get("lf")]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="챗봇 질문 500개 채점표")
    ap.add_argument("--rules", action="store_true", help="모델 없이 규칙만")
    ap.add_argument("--prompt-label", choices=["production", "staging"], default=None, help="Langfuse 프롬프트 라벨(기본은 기존 설정)")
    ap.add_argument("--model", default=None, help="Ollama 모델 이름(없으면 .env 의 LF_CHAT_RAG_MODEL)")
    ap.add_argument("--only", default="", help="문항 번호(예: 1-50,201)")
    ap.add_argument("--group", default="", help="분류·수준 이름 일부")
    ap.add_argument("--lf", action="store_true", help="Langfuse 고정 50문항만")
    ap.add_argument("--trace", action="store_true", help="Langfuse 기록 켬(기본은 끔 — 월 5만 단위 한도)")
    ap.add_argument("--record", action="store_true", help="일부만 돌려도 엑셀 단계로 기록")
    ap.add_argument("--note", default="", help="단계 정보 메모")
    ap.add_argument("--excel-only", action="store_true", help="실행 없이 엑셀만 다시 만듦")
    ap.add_argument("--questions", default=str(QUESTIONS))
    args = ap.parse_args(argv)
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    items = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    if args.prompt_label:
        os.environ['LF_PROMPT_LABEL'] = args.prompt_label
        if not (os.environ.get('LF_PROMPT_FETCH') or '').strip():
            os.environ['LF_PROMPT_FETCH'] = '1'    # 읽기만 켜고 trace 전송 여부는 --trace 그대로
    added = pull_overrides_from_excel()
    if added:
        print(f"엑셀 '사람 판정' {added}줄을 반영했어요")
    if args.excel_only:
        build_excel(items, load_runs())
        print(f"엑셀을 다시 만들었어요: {XLSX}")
        return 0
    os.environ.update(SIM_ENV)
    if not args.trace:
        os.environ["LF_LANGFUSE"] = "0"
    if args.rules:
        os.environ.pop("LF_CHAT_RAG_MODEL", None)
    elif args.model:
        os.environ["LF_CHAT_RAG_MODEL"] = args.model
    if not args.rules and not os.environ.get("LF_CHAT_RAG_MODEL"):
        print("모델 이름이 없어요 — --model midm-2.0-mini 처럼 주거나, 모델 없이 돌리려면 --rules")
        return 2
    if not args.rules:
        from tools.chat_live_check import installed_models, model_probe, model_ready
        why = model_ready(os.environ["LF_CHAT_RAG_MODEL"], installed_models()) or model_probe(os.environ["LF_CHAT_RAG_MODEL"])
        if why:
            print(why)
            return 2
    chosen = pick(items, args.only, args.group, args.lf)
    partial = len(chosen) != len(items)
    print(f"문항 {len(chosen)}개 · {'규칙만' if args.rules else os.environ['LF_CHAT_RAG_MODEL']} · Langfuse {'켬' if args.trace else '끔'}")
    runner, results, t0 = Runner(), [], time.perf_counter()
    started = dt.datetime.now()
    for it in chosen:
        x = runner.run_item(it)
        results.append(x)
        print(f"[{it['no']:3}] {'1' if x['score'] else '0'} {x['seconds']:5.1f}초 {it['group']} · {it['turns'][0].get('say', '')[:40]}")
        for w in x["why"][:3]:
            print("        ", w)
    total = sum(x["score"] for x in results)
    print(f"\n합계 {total}/{len(results)} ({total / max(len(results), 1):.1%}) · {round((time.perf_counter() - t0) / 60, 1)}분")
    if partial and not args.record:
        print("일부 문항만 돌려서 엑셀 단계로는 기록하지 않았어요(기록하려면 --record)")
        return 0
    RUNS.mkdir(parents=True, exist_ok=True)
    step = next_step_name([r["meta"]["step"] for r in load_runs()], started)
    meta = {"step": step, "started": started.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.perf_counter() - t0, 1),
            "commit": git_commit(), "model": model_info(args.rules), "note": args.note + (" (일부 문항)" if partial else ""),
            "questions": len(chosen), "trace": args.trace}
    fname = started.strftime("%Y%m%d-%H%M%S") + ".json"
    (RUNS / fname).write_text(json.dumps({"meta": meta, "results": results}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    build_excel(items, load_runs())
    print(f"단계 '{step}' 기록: evaluation/runs/{fname} · 엑셀 {XLSX.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
