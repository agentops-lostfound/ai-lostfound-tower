"""챗봇 모델 비교 (LLMOps, LF-5 · 11/5 변재원)

한줄 설명: 같은 이용 안내 질문 묶음(evaluation/guidance_questions.json)을 여러 Ollama 모델로 돌려
"정답 상태를 지켰나 · 모델 답을 몇 번 썼나 · 얼마나 걸렸나"를 표 하나로 비교한다. .env LF_CHAT_RAG_MODEL 을 고르기 전에 쓴다.

사용법 (교육원 PC, 저장소 폴더, .venv, Ollama 켠 상태)
    python tools/chat_model_bench.py                                              # 모델 없음(문서 원문) 기준만
    python tools/chat_model_bench.py --models exaone3.5:2.4b,qwen3-vl:4b-instruct      # 11/6 추천 비교
    python tools/chat_model_bench.py --models qwen3-vl:2b-instruct --limit 10 --out data/reports/chat_bench.md
    python tools/chat_model_bench.py --models exaone3.5:2.4b,qwen3:4b-instruct-2507-q4_K_M --rating data/reports/chat_rating.csv   # 11/6 사람 품질 평가표
- --rating: 모델 이름을 A·B·C 로 가린 답변 비교표(CSV, 엑셀로 열림)와 정답 열쇠(같은 이름 .key.json)를 만든다.
  모델이 실제로 답한 질문만 최대 20개. 사람이 정확성·자연스러움을 1~5점으로 적은 뒤 열쇠를 열어 모델별 평균을 낸다
- "none" 은 모델 없이 문서 문단 그대로 답하는 기준선이다(항상 맨 앞에 넣음)
- 모델은 승인된 문단 번호만 고른다(chat_rag.GroundedRag). 운영값 미정·주제 밖 질문은 모델을 부르지 않는다
- 질문 원문은 이미 저장소에 있는 평가 질문이고, 결과 파일에는 숫자와 틀린 질문만 적는다

용어
- 모델 사용: 모델이 고른 문단이 검증을 통과해 답에 쓰인 비율(generation_status=generated)
- 대체: 모델이 꺼졌거나 형식이 틀려 문서 원문으로 답한 경우(…_fallback)
- 첫 질문은 모델을 메모리에 올리는 시간이 길어 시간 계산에서 뺀다(--no-warmup 으로 끔)
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.chat_metrics import _pct  # noqa: E402

QUESTIONS = ROOT / "evaluation" / "guidance_questions.json"
BASELINE = "none"


def load_cases(limit: int | None = None) -> list[dict]:
    cases = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    return cases[:limit] if limit else cases


def passed(case: dict, res: dict) -> bool:
    """기존 평가(evaluation/evaluate_guidance.py case_passed)와 같은 기준"""
    from evaluation.evaluate_guidance import case_passed
    return case_passed(case, res)


def run_model(model: str, cases: list[dict], request=None, warmup: bool = True, clock=time.perf_counter) -> dict:
    """모델 하나로 질문 묶음을 돌린다. request 를 바꿔 끼우면 Ollama 없이 시험할 수 있다."""
    from agents.chat_rag import GroundedRag
    from agents.guidance import Guidance
    rag = GroundedRag(Guidance(), None if model == BASELINE else model, request=request)
    if warmup and model != BASELINE:
        first = next((c for c in cases if c["expected_status"] == "answered"), None)
        if first:
            try:
                rag.ask(first["question"])
            except ValueError:
                pass
    gen, all_ms, called_ms, wrong, answers = Counter(), [], [], [], []
    ok = 0
    for case in cases:
        t0 = clock()
        try:
            res = rag.ask(case["question"])
        except ValueError:                      # 너무 긴 질문 등 입력 거절
            res = {"status": "rejected", "sources": [], "answer": "", "generation_status": "rejected"}
        ms = (clock() - t0) * 1000
        all_ms.append(ms)
        status = res.get("generation_status", "not_needed")
        gen[status] += 1
        if status not in ("not_needed", "model_not_configured", "rejected", "fixed_policy_text",   # 시연 운영 기준은 모델을 안 부름
                          "guided_question", "off_topic", "retrieval_clarification"):          # 11/6 규칙 되묻기·주제 밖도 모델 안 부름
            called_ms.append(ms)                 # 모델을 실제로 부른 질문
        answers.append({"question": case["question"], "answer": res.get("answer", ""),
                        "generated": status in ("generated", "generated_clarification")})
        if passed(case, res):
            ok += 1
        else:
            wrong.append({"question": case["question"], "expected": case["expected_status"], "got": res.get("status")})
    called = len(called_ms)
    return {"model": model, "total": len(cases), "passed": ok,
            "passed_pct": round(100 * ok / len(cases)) if cases else None,
            "model_called": called, "generated": gen["generated"] + gen["generated_clarification"],   # 11/6 sLLM 되묻기도 모델 사용
            "generated_pct": round(100 * (gen["generated"] + gen["generated_clarification"]) / called) if called else None,
            "fallback": sum(v for k, v in gen.items() if k.endswith("_fallback")),
            "avg_ms": round(sum(called_ms or all_ms) / len(called_ms or all_ms), 1) if (called_ms or all_ms) else None,
            "p50_ms": _pct(called_ms or all_ms, 50), "p95_ms": _pct(called_ms or all_ms, 95),
            "generation_status": dict(gen.most_common()), "wrong": wrong, "answers": answers}


def write_rating(rows: list[dict], path: Path, limit: int = 20, seed: int | None = None) -> dict:
    """사람 품질 평가표: 모델 이름을 가린 글자(A,B,…)로 답을 나란히. 열쇠는 path 옆 .key.json. 돌려줌: 열쇠"""
    models = [r for r in rows if r["model"] != BASELINE]
    order = list(range(len(models)))
    random.Random(seed).shuffle(order)
    letters = {chr(65 + i): models[j]["model"] for i, j in enumerate(order)}
    by_letter = {chr(65 + i): models[j] for i, j in enumerate(order)}
    picked = [i for i, a in enumerate(rows[0]["answers"])
              if any(m["answers"][i]["generated"] for m in models)][:limit]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:          # utf-8-sig: 엑셀에서 한글이 안 깨지게
        w = csv.writer(f)
        w.writerow(["번호", "질문"] + [x for L in letters for x in (f"답 {L}", f"점수 {L}(1~5)")])
        for n, i in enumerate(picked, 1):
            w.writerow([n, rows[0]["answers"][i]["question"]]
                       + [x for L in letters for x in (by_letter[L]["answers"][i]["answer"], "")])
    key = {"letters": letters, "questions": len(picked),
           "how": "점수 = 정확성(문서와 맞나)·자연스러움(사람 말 같나)을 합쳐 1~5. 다 적은 뒤 이 열쇠로 글자 → 모델"}
    path.with_suffix(".key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    return key


def report(rows: list[dict]) -> str:
    lines = ["# 챗봇 모델 비교", "",
             f"질문 {rows[0]['total']}개(evaluation/guidance_questions.json). 시간은 모델을 부른 질문 기준(기준선은 전체 질문).", "",
             "| 모델 | 상태 일치 | 모델 호출 | 모델 사용 | 대체 | 평균 ms | p50 ms | p95 ms |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        name = "없음(문서 원문)" if r["model"] == BASELINE else f"`{r['model']}`"
        used = "-" if r["model"] == BASELINE else f"{r['generated']}건({r['generated_pct']}%)" if r["generated_pct"] is not None else "0건"
        lines.append(f"| {name} | {r['passed']}/{r['total']}({r['passed_pct']}%) | {r['model_called']} | {used} | "
                     f"{r['fallback']} | {r['avg_ms']} | {r['p50_ms']} | {r['p95_ms']} |")
    notes = []
    for r in rows:
        if r["model"] != BASELINE and r["model_called"] and not r["generated"]:
            notes.append(f"- `{r['model']}`: 모델 답을 한 번도 쓰지 못함 — Ollama 가 꺼졌거나 모델이 설치되지 않았을 수 있음(`ollama list` 로 확인)")
        if r["wrong"]:
            sample = ", ".join(f"\"{w['question']}\"({w['expected']}→{w['got']})" for w in r["wrong"][:3])
            notes.append(f"- {'기준선' if r['model'] == BASELINE else r['model']} 상태 불일치 {len(r['wrong'])}건: {sample}")
    if notes:
        lines += ["", "## 참고"] + notes
    lines += ["", "고르는 법: 상태 일치가 기준선보다 낮으면 탈락 → 남은 것 중 모델 사용 비율이 높고 p95 가 짧은 모델."]
    return "\n".join(lines)


def main(argv=None, request=None) -> str:
    p = argparse.ArgumentParser(description="챗봇 Ollama 모델 비교(이용 안내 질문 묶음)")
    p.add_argument("--models", default="", help="쉼표로 구분한 Ollama 모델 이름(기준선 none 은 자동 포함)")
    p.add_argument("--limit", type=int, default=None, help="앞에서부터 질문 N개만")
    p.add_argument("--out", type=Path, default=None, help="마크다운 결과 저장 경로")
    p.add_argument("--json", type=Path, default=None, help="숫자 전체를 JSON 으로 저장")
    p.add_argument("--no-warmup", action="store_true", help="첫 질문 예열을 하지 않음")
    p.add_argument("--rating", type=Path, default=None, help="사람 품질 평가표 CSV 경로(모델 이름 가림, 열쇠는 .key.json)")
    a = p.parse_args(argv)
    models = [BASELINE] + [m.strip() for m in a.models.split(",") if m.strip() and m.strip() != BASELINE]
    cases = load_cases(a.limit)
    rows = []
    for m in models:
        print(f"[{m}] 질문 {len(cases)}개 실행 중…", file=sys.stderr)
        rows.append(run_model(m, cases, request=request, warmup=not a.no_warmup))
    text = report(rows)
    if a.rating:
        key = write_rating(rows, a.rating)
        text += f"\n\n사람 평가표: {a.rating} (질문 {key['questions']}개, 모델 이름은 {a.rating.with_suffix('.key.json').name} 에)"
    for path, body in ((a.out, text), (a.json, json.dumps(rows, ensure_ascii=False, indent=2))):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    print(text)
    return text


if __name__ == "__main__":
    main()
