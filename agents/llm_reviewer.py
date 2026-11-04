"""메인 AI LLM 검토(Ollama 로컬 모델) — LF-14.

한줄 설명: 반환 직전 기록을 LLM에게 한 번 더 보여 주고 "이상하면 보류"만 받는다. 승인 권한은 없다.

- Ollama(PC에서 AI 모델을 돌리는 프로그램)의 /api/chat 에 요청한다. 인터넷·유료 API가 필요 없다.
- .env: OLLAMA_URL(기본 http://localhost:11434), MAIN_AI_MODEL(기본 qwen3-vl:4b-instruct), OLLAMA_KEEP_ALIVE(기본 5m)
- 주의(11/4): 비전 특징 추출은 Qwen3-VL-2B(Hugging Face, NF4)로 확정 — 이 검토 모델(Ollama 4B Q4 약 3.3GB)과 다른 모델이다.
  켜면 GPU 메모리를 더 쓰므로 시연 PC(RTX 3050 6GB)에서는 끈다(TOWER_REVIEWER 비움). 켤 때는 비전·VLA와 동시에 올리지 않는다
- LLM에는 개인정보를 보내지 않는다(지금 보내는 값: 사례 번호·접수 번호·상태).
- LLM이 응답하지 않거나 형식이 틀리면 on_error 값(기본 "hold" = 직원 확인)으로 처리한다.
- 코드 기본은 꺼짐(run_return 의 reviewer=None). 시연 PC 측정(instruct판)에서 잘못된 보류 0건 · 평균 2.7초라 시연에서는 켜도 된다.
  켤 때는 시작 전에 `python evaluation/run_cases.py --reviewer` 로 모델을 미리 올려 둔다(처음 올리기 약 7초). Ollama가 꺼져 있으면 모든 반환이 직원 확인으로 넘어간다
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

SYSTEM = (
    "너는 지하철 분실물 반환을 검토하는 보조 AI다. 승인할 권한은 없고, 기록에 이상한 점이 있을 때만 보류를 요청한다. "
    "반드시 JSON 한 줄로만 답한다: {\"verdict\": \"ok\" 또는 \"hold\", \"note\": \"이유 한 문장\"}"
)


class OllamaReviewer:
    def __init__(self, url: str | None = None, model: str | None = None, timeout: float | None = None, on_error: str = "hold"):
        try:   # .env 의 OLLAMA_URL·MAIN_AI_MODEL 읽기(없어도 기본값으로 동작)
            from tools.envfile import load_env
            load_env()
        except Exception:
            pass
        self.url = (url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        self.model = model or os.environ.get("MAIN_AI_MODEL") or "qwen3-vl:4b-instruct"
        self.keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE") or "5m"
        # 생각(thinking) 모드는 끈다. 주의: qwen3-vl:4b 는 생각 전용판이라 끄라고 해도 무시되고 답마다 약 10초 걸림.
        # instruct판(qwen3-vl:4b-instruct)은 시연 PC에서 답 22토큰 · 평균 2.7초 · 잘못된 보류 0건(11/2 측정)
        self.think = (os.environ.get("REVIEWER_THINK") or "false").strip().lower() == "true"
        self.timeout = timeout or float(os.environ.get("REVIEWER_TIMEOUT") or 60)   # 첫 호출은 모델을 GPU에 올리느라 느림
        self.durations: list[float] = []   # 호출마다 걸린 초(평균·최대 측정용)
        self.stats: list[dict] = []        # Ollama가 알려 주는 시간 내역(어디서 느린지)
        self.on_error = on_error if on_error in ("ok", "hold") else "hold"

    def _ask(self, summary: dict) -> str:
        body = {
            "model": self.model, "stream": False, "format": "json", "keep_alive": self.keep_alive, "think": self.think,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(summary, ensure_ascii=False)}],
            "options": {"temperature": 0},
        }
        req = urllib.request.Request(f"{self.url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
        ns = 1e9   # Ollama 시간 값은 나노초
        self.stats.append({
            "load_s": round(data.get("load_duration", 0) / ns, 2),            # 모델 올리기
            "prompt_tokens": data.get("prompt_eval_count", 0),
            "prompt_s": round(data.get("prompt_eval_duration", 0) / ns, 2),   # 질문 읽기
            "out_tokens": data.get("eval_count", 0),
            "out_s": round(data.get("eval_duration", 0) / ns, 2),             # 답 쓰기
            "thinking_chars": len(data["message"].get("thinking") or ""),
        })
        return data["message"]["content"]

    def warmup(self) -> float:
        """모델을 미리 GPU에 올려 둔다(첫 호출 지연을 측정에서 빼기 위해). 걸린 초를 돌려준다."""
        t = time.perf_counter()
        try:
            self._ask({"case": "warmup"})
        except Exception:
            pass
        return round(time.perf_counter() - t, 2)

    def __call__(self, summary: dict) -> tuple[str, str]:
        t = time.perf_counter()
        try:
            data = json.loads(self._ask(summary))
            verdict = data.get("verdict")
            if verdict not in ("ok", "hold"):
                raise ValueError("verdict 형식 오류")
            return verdict, str(data.get("note", ""))[:200]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            return self.on_error, f"LLM 검토 실패({type(e).__name__})"
        finally:
            self.durations.append(round(time.perf_counter() - t, 2))
