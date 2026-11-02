"""메인 AI LLM 검토(Ollama 로컬 모델) — LF-14.

한줄 설명: 반환 직전 기록을 LLM에게 한 번 더 보여 주고 "이상하면 보류"만 받는다. 승인 권한은 없다.

- Ollama(PC에서 AI 모델을 돌리는 프로그램)의 /api/chat 에 요청한다. 인터넷·유료 API가 필요 없다.
- .env: OLLAMA_URL(기본 http://localhost:11434), MAIN_AI_MODEL(기본 qwen3:4b — 이름은 `ollama list`로 확인, 추정)
- LLM에는 개인정보를 보내지 않는다(접수 번호·상태·공개 특징·매칭 점수만).
- LLM이 응답하지 않거나 형식이 틀리면 on_error 값(기본 "hold" = 직원 확인)으로 처리한다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

SYSTEM = (
    "너는 지하철 분실물 반환을 검토하는 보조 AI다. 승인할 권한은 없고, 기록에 이상한 점이 있을 때만 보류를 요청한다. "
    "반드시 JSON 한 줄로만 답한다: {\"verdict\": \"ok\" 또는 \"hold\", \"note\": \"이유 한 문장\"}"
)


class OllamaReviewer:
    def __init__(self, url: str | None = None, model: str | None = None, timeout: float = 20.0, on_error: str = "hold"):
        self.url = (url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        self.model = model or os.environ.get("MAIN_AI_MODEL") or "qwen3:4b"
        self.timeout = timeout
        self.on_error = on_error if on_error in ("ok", "hold") else "hold"

    def _ask(self, summary: dict) -> str:
        body = {
            "model": self.model, "stream": False, "format": "json",
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": json.dumps(summary, ensure_ascii=False)}],
            "options": {"temperature": 0},
        }
        req = urllib.request.Request(f"{self.url}/api/chat", data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as res:
            return json.loads(res.read().decode("utf-8"))["message"]["content"]

    def __call__(self, summary: dict) -> tuple[str, str]:
        try:
            data = json.loads(self._ask(summary))
            verdict = data.get("verdict")
            if verdict not in ("ok", "hold"):
                raise ValueError("verdict 형식 오류")
            return verdict, str(data.get("note", ""))[:200]
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError, json.JSONDecodeError) as e:
            return self.on_error, f"LLM 검토 실패({type(e).__name__})"
