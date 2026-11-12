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
from agents.contracts import PHONE_RE, without_non_phone
from agents.local_model import ask_local_model
from agents.observability import step

INTENTS = ("service", "greeting", "thanks", "off_topic")
WORKERS = ("guidance", "item_search")
SERVICE_WORDS = re.compile(r"잃어|분실|주웠|주운|습득|찾|맡|받|수령|보관|키오스크|본센터|센터|신분|개인정보|연락처|후보|물건|"
                           r"지갑|휴대폰|핸드폰|휴대전화|스마트폰|전화기|아이폰|갤럭시|폰|usb|립밤|핸드크림|보조배터리|배터리|로봇|직원|역|운영|시간|예약|대리")
# 물건 검색을 허용할 신호: 물건 종류 낱말 또는 찾기·검색 말(없으면 planner 가 item_search 를 골라도 뺀다 — 실측 11/7: 모델이 거의 항상 둘 다 고름)
# 11/9 휴대폰 낱말은 공용 규칙(contracts.PHONE_RE — 앞말 붙은 '이어폰·헤드폰'의 '폰' 제외)을 쓰고, 검사 전에 휴대폰이 아닌 말을 지운다
ITEM_WORDS = re.compile(r"지갑|카드지갑|usb|유에스비|립밤|핸드크림|보조배터리|배터리|찾아|찾고|찾을|검색|후보|" + PHONE_RE.pattern)
GREETING_REPLY = ("안녕하세요! 지하철 분실물 안내 도우미예요. 잃어버린 물건 찾기, 주운 물건 맡기기, 물건 받는 방법을 물어보세요. "
                  "예: \"빨간 립밤 잃어버렸어요\", \"본센터에서 어떻게 받아요?\"")
THANKS_REPLY = "도움이 됐다니 다행이에요. 더 궁금한 점이 있으면 언제든 물어보세요."


# 습득자 쪽 질문(맡기기·놓는 법): 분실물 후보 검색이 필요 없다
FOUND_SIDE = re.compile(r"주웠|주운|주워|맡기|맡겨|맡길|넣어|넣는|넣으|놓는|놓아|놓으|두는|습득|올려")


class AgentBrain:
    def __init__(self, model: str, request=None, timeout: float = 30.0):
        self.model = model
        self.request = request or (lambda payload: ask_local_model(payload, timeout=timeout))

    def _ask(self, name: str, agent: str, schema: dict, user: dict) -> dict | None:
        """agent: 그래프 칸 이름(prompts.AGENT_PROMPTS). 11/9 칸마다 Langfuse config 의 model·temperature·use_llm 을 따른다"""
        system, prompt_obj, cfg = prompts.resolve(agent, model=self.model, temperature=0)
        if not cfg["use_llm"] or not cfg["model"]:
            return None                               # 이 칸은 모델을 쓰지 않음 → 규칙
        from agents.chat_progress import notify      # 11/8 진행률 알림만(동작 그대로, agents/chat_progress.py)
        notify("route")
        payload = {"model": cfg["model"], "stream": False, "format": schema,
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
                   "options": {"temperature": cfg["temperature"], "num_predict": 64, "num_ctx": 4096}, "keep_alive": "5m"}
        usage = prompts.record_usage(agent, cfg, prompt_obj)
        with step(name, as_type="generation", model=cfg["model"], input=payload["messages"], prompt=prompt_obj,
                  metadata={'prompt_usage': usage},
                  model_parameters={"temperature": cfg["temperature"], "num_predict": 64}) as gen:
            started = time.perf_counter()
            try:
                out = self.request(payload)
                content = out["message"]["content"]
                parsed = json.loads(content)
            except Exception as e:          # 모델 꺼짐·형식 오류 → 규칙으로
                gen.update(level="WARNING", status_message=type(e).__name__)
                return None
            traced = parsed
            if agent == "supervisor":
                from agents.chat_supervisor import safe_proposal
                traced = safe_proposal(parsed)
            gen.update(output=traced, metadata={"seconds": round(time.perf_counter() - started, 3), 'prompt_usage': usage})
            return parsed if isinstance(parsed, dict) else None

    def coordinate(self, question: str, history: list | None = None) -> tuple[str, bool] | None:
        """(intent, 모델이 판단했는지) 또는 None(모델 못 씀). 서비스 낱말이 있으면 모델을 부르지 않고 service(규칙)"""
        if SERVICE_WORDS.search(question.lower()):
            return "service", False
        schema = {"type": "object", "additionalProperties": False, "required": ["intent"],
                  "properties": {"intent": {"type": "string", "enum": list(INTENTS)}}}
        parsed = self._ask("coordinator-llm", "coordinator", schema,
                           {"previous_questions": [h for h in (history or []) if isinstance(h, str)][-2:], "message": question})
        intent = (parsed or {}).get("intent")
        if intent not in INTENTS:
            return None
        if intent in ("greeting", "thanks") and len(re.sub(r"\s", "", question)) > 20:   # 긴 말은 인사만이 아님
            return "service", True
        # 11/8 에이전트 무작위 시험: "토요일에도 하나요?"·"다른 사람 주소 알려줘"에 모델이 thanks → "도움이 됐다니 다행이에요"
        # 물음표·의문형 끝·부탁 말이 있으면 인사·감사로 보지 않는다
        if intent in ("greeting", "thanks") and re.search(
                r"[?？]|나요|까요|가요|어요\s*$|에요\s*$|뭐|누구|어디|언제|어떻게|왜|알려|줘|주세요|돼요?\??\s*$|되나|하라\s*$|있어|없어|잇어|알수|please|help|pls|안\s*돼|\?", question):
            return "service", True
        if intent == "thanks" and re.search(r"안녕|하이|ㅎㅇ", question) and not re.search(r"고마|감사", question):
            intent = "greeting"                     # 11/8 가짜 모델 시험: "안녕하세요"에 감사 답
        elif intent == "greeting" and re.search(r"고마|감사", question):
            intent = "thanks"
        return intent, True

    def plan(self, question: str, history: list | None = None, rule_steps: list | None = None) -> list | None:
        """일꾼 순서 또는 None. 규칙이 찾은 일꾼(rule_steps)은 반드시 남긴다(모델은 더하기만)"""
        schema = {"type": "object", "additionalProperties": False, "required": ["steps"],
                  "properties": {"steps": {"type": "array", "minItems": 1, "maxItems": 2,
                                           "items": {"type": "string", "enum": list(WORKERS)}}}}
        parsed = self._ask("planner-llm", "planner", schema,
                           {"previous_questions": [h for h in (history or []) if isinstance(h, str)][-4:], "question": question})
        steps = (parsed or {}).get("steps")
        if not isinstance(steps, list) or not steps or any(s not in WORKERS for s in steps):
            return None
        out = []
        for s in list(steps) + list(rule_steps or []):
            if s in WORKERS and s not in out:
                out.append(s)
        if "item_search" in out and "item_search" not in (rule_steps or []) and (
                not ITEM_WORDS.search(without_non_phone(question)) or FOUND_SIDE.search(re.sub(r"\s+", "", question))):
            out.remove("item_search")        # 11/9 실제 모델 시험: "휴대폰은 상자에 어떻게 넣어요?"(습득자 질문)에 분실물 검색을 붙임
        if not out:
            out = ["guidance"]
        if "item_search" in out and "guidance" in out:       # 찾기 결과를 먼저, 안내를 뒤에(화면 읽기 순서)
            out = ["item_search", "guidance"]
        return out


    def extract_slots(self, question: str, kind: str, schema: dict) -> dict | None:
        """11/9 대화 접수: 규칙이 못 읽은 빈칸(품목·색·역)을 고를 값 목록(schema enum) 안에서만 채움. 값 검사는 부르는 쪽(chat_intake)이 다시 함"""
        return self._ask("intake-extract-llm", "intake", schema, {"kind": kind, "message": question})

    def choose(self, agent: str, allowed: list, rule: str, context: dict) -> str | None:
        """11/9 규칙 칸 보조(use_llm 기본 끔): 규칙이 허용한 값(allowed) 안에서 하나만 고르게 한다(JSON 스키마 고정).
        목록 밖·실패·꺼짐이면 None → 부르는 쪽이 규칙 결과(rule)를 그대로 쓴다(규칙이 거부권)"""
        allowed = [a for a in allowed if isinstance(a, str)]
        if len(allowed) < 2 or rule not in allowed:
            return None
        schema = {"type": "object", "additionalProperties": False, "required": ["choice"],
                  "properties": {"choice": {"type": "string", "enum": allowed}}}
        parsed = self._ask(f"{agent}-llm", agent, schema, {"allowed": allowed, "rule_next": rule, **context})
        choice = (parsed or {}).get("choice")
        return choice if choice in allowed else None

    def search_slots(self, question: str) -> dict | None:
        """11/9 item_search 일꾼(use_llm 켰을 때): 규칙이 못 읽은 품목·색을 운영 품목·색 목록 안에서만 고른다.
        목록 밖·'모름'·실패면 None. 색은 말에 색 낱말이 있을 때만 받는다(부르는 쪽 검사, intake 와 같은 원칙)"""
        from agents.contracts import ACTIVE_CATEGORIES, COLORS
        schema = {"type": "object", "additionalProperties": False, "required": ["category", "color"],
                  "properties": {"category": {"type": "string", "enum": list(ACTIVE_CATEGORIES) + ["모름"]},
                                 "color": {"type": "string", "enum": [c for c in COLORS if c != "기타"] + ["모름"]}}}
        parsed = self._ask("item-search-llm", "item_search", schema, {"message": question})
        if not isinstance(parsed, dict):
            return None
        out = {k: v for k, v in parsed.items() if k in ("category", "color") and isinstance(v, str) and v != "모름"}
        return out or None

    def supervise(self, allowed: list, context: dict) -> dict | None:
        """감독 제안만 생성. 실제 후보 일치 검사는 chat_supervisor.validate가 한다."""
        from agents.chat_supervisor import output_schema
        schema = output_schema(allowed)
        return self._ask("supervisor-llm", "supervisor", schema,
                         {**context, "allowed": allowed})


__all__ = ["AgentBrain", "GREETING_REPLY", "THANKS_REPLY", "INTENTS", "WORKERS"]
