"""챗봇 모델을 그래픽카드(GPU)와 CPU 로 각각 돌려 걸리는 시간을 잰다 (11/8 변재원, GPU 6GB 안전 확인용).

한줄 설명: 로봇·Qwen 이 GPU 사용권을 쥔 동안 챗봇(Mi:dm)은 CPU 로 답한다(agents/local_model.py). 그때 답이 몇 초 걸리는지
이 PC 에서 직접 재서 시연에 쓸 수 있는지 판단한다. 교육원 관제탑 PC 에서 꼭 한 번 돌려 docs/design/gpu_lease.md §5 표에 적는다.

실행(저장소 폴더, .venv): python tools/ollama_cpu_bench.py            (모델: .env LF_CHAT_RAG_MODEL, 없으면 midm-2.0-mini)
- 같은 질문을 CPU 2번 → GPU 2번 묻는다(각 첫 번째는 모델을 다시 올리는 시간 포함). 답 내용은 출력하지 않는다
- 끝나면 Ollama 모델을 내려 그래픽카드를 비운다
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUESTION = "분실물 센터에서 물건을 찾을 때 필요한 준비물을 세 문장으로 설명해 줘."


def ask(model: str, cpu: bool, num_predict: int = 170) -> dict:
    body = {"model": model, "stream": False, "keep_alive": "5m", "messages": [{"role": "user", "content": QUESTION}],
            "options": {"temperature": 0, "num_predict": num_predict, "num_ctx": 4096, **({"num_gpu": 0} if cpu else {})}}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    with opener.open(req, timeout=300) as r:
        out = json.loads(r.read())
    ms = lambda k: round((out.get(k) or 0) / 1e6)  # noqa: E731
    return {"where": "CPU" if cpu else "GPU", "seconds": round(time.perf_counter() - started, 1),
            "load_ms": ms("load_duration"), "prompt_ms": ms("prompt_eval_duration"), "gen_ms": ms("eval_duration"),
            "tokens": out.get("eval_count")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="챗봇 모델 CPU·GPU 답 시간 재기")
    ap.add_argument("--model")
    a = ap.parse_args(argv)
    sys.path.insert(0, str(ROOT))
    try:
        from tools.envfile import load_env
        load_env()
    except Exception:
        pass
    model = a.model or os.environ.get("LF_CHAT_RAG_MODEL") or "midm-2.0-mini"
    print(f"모델 {model} · 질문 1개 · 답 최대 170토큰(챗봇 실제 답 중앙값 172토큰, Langfuse 11/8)")
    rows = []
    for cpu in (True, True, False, False):
        try:
            r = ask(model, cpu)
        except Exception as e:
            print(f"실패({type(e).__name__}) — Ollama 가 켜져 있고 모델이 있는지 확인: ollama list")
            return 2
        rows.append(r)
        print(f"{r['where']}: {r['seconds']}초 (모델 올리기 {r['load_ms']}ms · 질문 읽기 {r['prompt_ms']}ms · "
              f"답 쓰기 {r['gen_ms']}ms · {r['tokens']}토큰)")
    try:
        from agents.local_model import unload_local_models
        unload_local_models()
    except Exception:
        pass
    cpu_warm = rows[1]["seconds"]
    print(f"정리: CPU 로 답할 때 약 {cpu_warm}초(모델이 올라가 있을 때). 웹 챗봇 기다림 한도 40초 안이면 사용권 중에도 답함")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
