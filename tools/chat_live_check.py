"""챗봇 실제 모델 회귀 시험 (LF-5 · 11/9 변재원)

한줄 설명: 사용자가 실제로 칠 법한 질문 묶음을 진짜 모델(Ollama)이 붙은 챗봇 전체 경로에 넣고,
답에 꼭 있어야 할 말·없어야 할 말·나오면 안 되는 상태를 자동으로 확인한다.

왜: 단위 시험(python -m unittest)은 모델 없이 규칙만 본다. 11/9 진짜 Mi:dm 으로 12문항을 넣자 4개가 엉뚱했다
(답할 수 있는 질문을 되물음·버튼 글자 깨짐·오타를 서비스 밖으로 봄·이어 묻기 모순). 모델·프롬프트·검사기를 고칠 때마다 이걸 돌린다.

사용법 (저장소 폴더, .venv, Ollama 켠 상태)
    python tools/chat_live_check.py                         # .env 의 LF_CHAT_RAG_MODEL
    python tools/chat_live_check.py --model midm-2.0-mini --out 결과.json
    python tools/chat_live_check.py --only 4,8              # 몇 번 문항만
- 질문 묶음: evaluation/chat_live_questions.json — {q, history?, any?(하나라도 있어야), not?(없어야), status_not?(나오면 안 되는 상태)}
- 모든 문항 공통 검사: 빈 답 아님 · 깨진 낱말 끝("있요·없요") 없음 · 영어 주제 이름(finder_privacy 등) 없음
- 결과: 문항별 통과/실패와 이유, 걸린 시간, 끝에 합계. 실패가 있으면 종료 코드 1
- 그래픽카드에서 문항당 약 1~3초(추정), 클라우드 CPU 에서는 3~40초
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
QUESTIONS = ROOT / "evaluation" / "chat_live_questions.json"
BROKEN = re.compile(r"[있없]요|[가-힣]{2,}요요")
TOPIC_NAME = re.compile(r"\b[a-z]+_[a-z_]+\b")


def check(item: dict, res: dict) -> list[str]:
    """문항 하나의 실패 이유 목록(비면 통과)"""
    answer = res.get("answer") or ""
    shown = answer + " " + " ".join(str(c) for c in res.get("choices") or [])
    why = []
    if not answer.strip():
        why.append("빈 답")
    if item.get("any") and not any(w in answer for w in item["any"]):
        why.append("꼭 있어야 할 말 없음: " + "/".join(item["any"]))
    for w in item.get("not", []):
        if w in shown:
            why.append(f"나오면 안 되는 말: {w}")
    if res.get("generation_status") in item.get("status_not", []):
        why.append(f"나오면 안 되는 상태: {res.get('generation_status')}")
    if BROKEN.search(shown):
        why.append("깨진 낱말 끝: " + BROKEN.search(shown).group(0))
    if TOPIC_NAME.search(shown):
        why.append("영어 주제 이름: " + TOPIC_NAME.search(shown).group(0))
    return why


def installed_models(base: str = "http://127.0.0.1:11434") -> list[str] | None:
    """Ollama 에 설치된 모델 이름들(Ollama 가 꺼져 있으면 None)"""
    import urllib.request
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=5) as r:
            return [m.get("name", "") for m in json.loads(r.read().decode("utf-8")).get("models", [])]
    except Exception:
        return None


def model_ready(name: str, names: list[str] | None) -> str:
    """시험을 시작해도 되면 "", 아니면 이유. 11/9 교육원 PC: 모델이 없는데도 문서 문장으로 '통과'(0.0초)처럼 보였다"""
    if names is None:
        return "Ollama 에 연결할 수 없어요 — Ollama 를 켜고(작업 표시줄 라마 아이콘) 다시 실행하세요"
    if name not in names and f"{name}:latest" not in names:
        return (f"Ollama 에 '{name}' 모델이 없어요(설치된 것: {', '.join(names) or '없음'}) — "
                "설치 안내 docs/ollama/README.md 2-B")
    return ""


def model_probe(name: str, request=None) -> str:
    """진짜 대화 한 번(/api/chat, JSON 형식)을 보내 본다. 되면 "", 안 되면 이유(HTTP 코드·Ollama 오류 문장 그대로).
    11/9 교육원 PC: 설치 목록(/api/tags)에는 모델이 있는데 문항마다 0.1초로 끝남 — 챗봇은 모델 오류를 조용히 규칙 답으로
    바꾸므로(chat_agents._ask) 겉으로는 원인이 안 보였다. 이 확인으로 진짜 오류 문장을 먼저 보여 준다"""
    import urllib.error
    from agents.local_model import ask_local_model
    ask = request or (lambda payload: ask_local_model(payload, timeout=180))
    payload = {"model": name, "stream": False, "format": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                                          "required": ["ok"]},
               "messages": [{"role": "user", "content": '{"ok": true} 를 그대로 답하세요'}],
               "options": {"temperature": 0, "num_predict": 16}, "keep_alive": "5m"}
    try:
        out = ask(payload)
        json.loads(out["message"]["content"])
        return ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read(2000).decode("utf-8", "replace")
        except Exception:
            body = ""
        return f"Ollama 가 HTTP {e.code} 로 거절: {body.strip()[:300]}"
    except Exception as e:
        return f"모델 대화 실패({type(e).__name__}: {str(e)[:200]})"


def run(bot, items: list[dict]) -> list[dict]:
    rows = []
    for no, item in items:
        t0 = time.perf_counter()
        try:
            res = bot.ask(item["q"], None, None, item.get("history") or [], session_id=f"live-check-{no:03d}")
        except Exception as e:              # 한 문항이 예외여도 나머지는 돈다
            res = {"answer": "", "generation_status": f"예외 {type(e).__name__}"}
        sec = round(time.perf_counter() - t0, 2)
        why = check(item, res)
        rows.append({"no": no, "q": item["q"], "ok": not why, "why": why, "seconds": sec,
                     "status": res.get("generation_status"), "path": res.get("agent_path"),
                     "answer": (res.get("answer") or "")[:300], "choices": res.get("choices") or []})
        mark = "통과" if not why else "실패"
        print(f"[{no:2}] {mark} {sec:5.1f}초 {item['q']}  ({res.get('generation_status')})")
        if why:
            print("      ", " / ".join(why))
            print("       답:", rows[-1]["answer"].replace("\n", " ")[:160])
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="챗봇 실제 모델 회귀 시험")
    ap.add_argument("--model", default=None, help="Ollama 모델 이름(없으면 .env 의 LF_CHAT_RAG_MODEL)")
    ap.add_argument("--only", default="", help="문항 번호(1부터, 쉼표로)")
    ap.add_argument("--out", default="", help="결과 JSON 저장 경로")
    args = ap.parse_args(argv)
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    if args.model:
        os.environ["LF_CHAT_RAG_MODEL"] = args.model
    if not os.environ.get("LF_CHAT_RAG_MODEL"):
        print("모델 이름이 없습니다 — --model midm-2.0-mini 처럼 주거나 .env 의 LF_CHAT_RAG_MODEL 을 채우세요")
        return 2
    why = model_ready(os.environ["LF_CHAT_RAG_MODEL"], installed_models())
    if why:
        print(why)
        return 2
    print("모델 대화 확인 중(처음이면 모델을 올리느라 30초~2분 걸릴 수 있음)…")
    why = model_probe(os.environ["LF_CHAT_RAG_MODEL"])
    if why:
        print("모델이 대화에 답하지 못해요 →", why)
        print("이 상태로 돌리면 챗봇이 규칙 답만 내서 0.1초처럼 보입니다. 위 오류 문장을 그대로 알려 주세요")
        return 2
    os.environ.setdefault("LF_LANGFUSE", "0")           # 시험 실행이 Langfuse 기록을 어지럽히지 않게
    from agents.chat_api import build_chatbot_from_env
    items = list(enumerate(json.loads(QUESTIONS.read_text(encoding="utf-8")), 1))
    if args.only:
        keep = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
        items = [(n, i) for n, i in items if n in keep]
    print(f"모델 {os.environ['LF_CHAT_RAG_MODEL']} · 문항 {len(items)}개")
    rows = run(build_chatbot_from_env(), items)
    ok = sum(r["ok"] for r in rows)
    secs = [r["seconds"] for r in rows]
    print(f"\n합계 {ok}/{len(rows)} 통과 · 시간 중앙 {statistics.median(secs):.1f}초 · 최대 {max(secs):.1f}초" if rows else "문항 없음")
    if rows and statistics.median(secs) < 0.5:
        print("⚠️ 시간 중앙이 0.5초 미만 — 모델이 실제로 불리지 않았을 수 있어요(괄호 안 상태가 모두 규칙 답인지 확인)")
    if args.out:
        Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
