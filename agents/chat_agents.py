"""챗봇 coordinator · planner — 모델(Mi:dm)이 판단 (LF-5 · 11/7 변재원, DeerFlow/LangManus 구조)

한줄 설명: coordinator 는 "인사·감사·주제 밖·서비스 질문" 중 무엇인지, planner 는 "어떤 일꾼(안내 문서·물건 검색)을
어떤 순서로 부를지"를 모델이 정한다. 모델이 꺼져 있거나 답이 이상하면 None 을 돌려주고, 챗봇은 기존 규칙으로 처리한다.

안전장치
- 모델 출력은 JSON 스키마(고를 수 있는 값 목록)로 묶는다 — 정해진 값 밖의 말을 할 수 없음
- coordinator 가 인사·감사라고 해도 서비스 낱말(잃어버/주웠/찾/본센터 …)이 있으면 서비스로 본다(잘못 끊지 않게)
- planner 는 규칙이 분명히 찾은 일꾼을 지울 수 없다(더하기만 가능) — 데모 질문이 엉뚱한 길로 가지 않게
- 관제(ops) 길은 모델이 열 수 없다(관리자 로그인 확인 뒤 규칙으로만)
"""
from __future__ import annotations

import json
import re
import time

from agents import prompts
from agents.local_model import ask_local_model
from agents.observability import step

INTENTS = ("service", "greeting", "thanks", "off_topic")
WORKERS = ("guidance", "item_search")
SERVICE_WORDS = re.compile(r"잃어|분실|주웠|주운|습득|찾|맡|받|수령|보관|키오스크|본센터|센터|신분|개인정보|연락처|후보|물건|"
                           r"지갑|휴대폰|핸드폰|폰|usb|립밤|핸드크림|보조배터리|배터리|로봇|직원|역|운영|시간|예약|대리")
# 물건 검색을 허용할 신호: 물건 종류 낱말 또는 찾기·검색 말(없으면 planner 가 item_search 를 골라도 뺀다 — 실측 11/7: 모델이 거의 항상 둘 다 고름)
ITEM_WORDS = re.compile(r"지갑|카드지갑|휴대폰|핸드폰|모형폰|폰|usb|유에스비|립밤|핸드크림|보조배터리|배터리|찾아|찾고|찾을|검색|후보")
GREETING_REPLY = ("안녕하세요! 지하철 분실물 안내 도우미예요. 잃어버린 물건 찾기, 주운 물건 맡기기, 물건 받는 방법을 물어보세요. "
                  "예: \"검정 지갑 잃어버렸어요\", \"본센터에서 어떻게 받아요?\"")
THANKS_REPLY = "도움이 됐다니 다행이에요. 더 궁금한 점이 있으면 언제든 물어보세요."


class AgentBrain:
    def __init__(self, model: str, request=None, timeout: float = 30.0):
        self.model = model
        self.request = request or (lambda payload: ask_local_model(payload, timeout=timeout))

    def _ask(self, name: str, prompt_name: str, schema: dict, user: dict) -> dict | None:
        system, prompt_obj = prompts.get(prompt_name)
        payload = {"model": self.model, "stream": False, "format": schema,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
                   "options": {"temperature": 0, "num_predict": 64, "num_ctx": 4096}, "keep_alive": "5m"}
        with step(name, as_type="generation", model=self.model, input=payload["messages"], prompt=prompt_obj,
                  model_parameters={"temperature": 0, "num_predict": 64}) as gen:
            started = time.perf_counter()
            try:
                out = self.request(payload)
                content = out["message"]["content"]
                parsed = json.loads(content)
            except Exception as e:          # 모델 꺼짐·형식 오류 → 규칙으로
                gen.update(level="WARNING", status_message=type(e).__name__)
                return None
            gen.update(output=parsed, metadata={"seconds": round(time.perf_counter() - started, 3)})
            return parsed if isinstance(parsed, dict) else None

    def coordinate(self, question: str, history: list | None = None) -> tuple[str, bool] | None:
        """(intent, 모델이 판단했는지) 또는 None(모델 못 씀). 서비스 낱말이 있으면 모델을 부르지 않고 service(규칙)"""
        if SERVICE_WORDS.search(question.lower()):
            return "service", False
        schema = {"type": "object", "additionalProperties": False, "required": ["intent"],
                  "properties": {"intent": {"type": "string", "enum": list(INTENTS)}}}
        parsed = self._ask("coordinator-llm", "chat-coordinator", schema,
                           {"previous_questions": [h for h in (history or []) if isinstance(h, str)][-2:], "message": question})
        intent = (parsed or {}).get("intent")
        if intent not in INTENTS:
            return None
        if intent in ("greeting", "thanks") and len(re.sub(r"\s", "", question)) > 20:   # 긴 말은 인사만이 아님
            return "service", True
        return intent, True

    def plan(self, question: str, history: list | None = None, rule_steps: list | None = None) -> list | None:
        """일꾼 순서 또는 None. 규칙이 찾은 일꾼(rule_steps)은 반드시 남긴다(모델은 더하기만)"""
        schema = {"type": "object", "additionalProperties": False, "required": ["steps"],
                  "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": 2,
                                           "items": {"type": "string", "enum": list(WORKERS)}}}}
        parsed = self._ask("planner-llm", "chat-planner", schema,
                           {"previous_questions": [h for h in (history or []) if isinstance(h, str)][-4:], "question": question})
        steps = (parsed or {}).get("steps")
        if not isinstance(steps, list) or not steps or any(s not in WORKERS for s in steps):
            return None
        out = []
        for s in list(steps) + list(rule_steps or []):
            if s in WORKERS and s not in out:
                out.append(s)
        if "item_search" in out and "item_search" not in (rule_steps or []) and not ITEM_WORDS.search(question.lower()):
            out.remove("item_search")
        if not out:
            out = ["guidance"]
        if "item_search" in out and "guidance" in out:       # 찾기 결과를 먼저, 안내를 뒤에(화면 읽기 순서)
            out = ["item_search", "guidance"]
        return out


__all__ = ["AgentBrain", "GREETING_REPLY", "THANKS_REPLY", "INTENTS", "WORKERS"]
