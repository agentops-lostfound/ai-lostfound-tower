"""챗봇 RAG + 로컬 sLLM (LF-5 · 11/5 정연우 → 11/6 변재원 sLLM·되묻기)

한줄 설명: 질문에 맞는 안내 문단을 찾고(검색, agents/chat_retrieval.py + 규칙 agents/guidance.py),
로컬 sLLM(Ollama, 11/7 결정 KT Mi:dm 2.0 Mini — docs/design/chatbot_sllm_rag.md §9)이 그 문단만 근거로 답하거나, 정보가 모자라면 되묻는다(유도 질문).

안전장치(모델 답이 하나라도 어기면 버리고 문서 문장 그대로 답함)
- 문단 번호는 실제로 찾은 문단만, 답에 나온 숫자는 고른 문단에 있는 숫자만(운영값을 지어내지 못함)
- 개인정보 모양·주소(URL)·지나치게 긴 답 금지, 시연 운영 기준 주제는 '시연 기준' 문구를 붙임
- 운영값이 문서에 없는 질문(policy_pending)은 모델을 부르지 않음
- 모델이 없거나(LF_CHAT_RAG_MODEL 비움) 꺼져 있어도 규칙 기반 되묻기(선택지 버튼)로 대화를 이어 감
"""
import json
import threading
import re
from agents.local_model import ask_local_model
from agents.support_security import has_private_pattern

MIN_SCORE = 0.13          # 이보다 낮으면 주제 밖 질문으로 보고 되묻지 않음(날씨·잡담 등, 11/6 측정)
DEMO_SUFFIX = " (프로젝트 시연 기준이며 실제 기관 안내가 아니에요.)"
MENU = ["물건을 잃어버렸어요", "물건을 주웠어요", "물건 받는 방법 알려줘", "운영시간 알려줘"]
# 잃어버림 → 무엇을? (품목 버튼을 누르면 물건 검색으로 이어짐)
LOST_RE = re.compile(r"잃어버|분실|두고내렸|놓고내렸|놓고왔|두고왔|없어졌|잃었")
LOST_CHOICES = ["지갑 잃어버렸어요", "휴대폰 잃어버렸어요", "USB 잃어버렸어요", "찾을 수 있는 물건 종류"]
# 11/7 규칙 문장 그대로 쓰는 주제: 모델이 바꿔 말하면 뜻이 틀어지는 규칙(실측: 4개 모델 38문항 비교, docs/design/chatbot_sllm_rag.md §9)
# 예) 습득자 연락처 "인계 완료 뒤 30일"을 "반환 보류 30일"로, "동의 시각"을 "분실 시각"으로, "전화번호 적지 마세요"를 "안 적어도 돼요"로
FIXED_TEXT_TOPICS = {"finder_contact", "masked_identity", "consent", "arrival", "privacy_input", "candidate_scope"}
# 11/7 저녁(사용자 결정): 규칙 주제도 모델이 직접 답하되 ① 주제별 핵심어 검사 ② 통과하면 답 아래 "근거: 원문 한 문장"
# 검사에 걸리면 문서 문장 그대로(fixed_rule_text). 핵심어 = 그 말이 빠지면 뜻이 틀어지는 말(하나라도 있으면 통과)
RULE_MUST = {"finder_contact": ("인계",), "arrival": ("1시간",), "candidate_scope": ("확정",), "masked_identity": ("가린",),
             "privacy_input": ("적지 말", "적지 마", "쓰지 말", "쓰지 마", "입력하지 마", "접수되지", "넣지 마", "적으시면 안"),
             "consent": ("종료", "진행하지", "받을 수 없", "진행되지", "받으실 수 없")}
RULE_NOT_START = {"arrival": ("네", "예")}           # "바로 받을 수 있나요?"에 "네"로 시작하면 뜻이 반대


def rule_answer_ok(answer: str, topics) -> bool:
    """규칙 주제 답의 핵심어 검사. topics: 근거 문단 주제들"""
    text = answer.strip()
    for t in topics:
        must = RULE_MUST.get(t)
        if must and not any(m in text for m in must):
            return False
        if any(text.startswith(w) for w in RULE_NOT_START.get(t, ())):
            return False
    return True


def first_sentence(text: str) -> str:
    """원문 첫 문장(근거 한 줄)"""
    m = re.match(r"(.+?[.?!](?:\s|$))", text.strip())
    return (m.group(1) if m else text.strip()).strip()


def topic_question(topic: str) -> str:
    """주제 → 그 주제로 답하는 질문(되묻기 버튼 글자). 규칙(agents/guidance.py)에 걸리는 말"""
    from agents.chat_conversation import TOPIC_LABELS
    return {"finder_contact": "습득자 연락처는 언제 지우나요?"}.get(topic, f"{TOPIC_LABELS.get(topic, topic)} 알려줘")


def numbers_supported(answer: str, evidence: str) -> bool:
    """답에 나온 숫자가 모두 근거 문단에 있는지(09:00·14일·30일 같은 운영값을 지어내지 못하게)"""
    have = set(re.findall(r"\d+", evidence))
    return all(n in have for n in re.findall(r"\d+", answer))


class GroundedRag:
    def __init__(self, guidance, model=None, request=None):
        from agents.chat_retrieval import Retriever
        self.guidance, self.model = guidance, model
        self.request = request or self._request
        self._lock = threading.Lock()
        self.retriever = Retriever(guidance.documents)

    @staticmethod
    def _request(payload):
        return ask_local_model(payload)

    def ask(self, question, history=None):
        """history: 같은 화면의 이전 사용자 질문(최대 4개, chat_conversation.checked_history 로 검사된 것). 모델에 맥락으로만 준다.
        여러 사람이 동시에 묻기 때문에 객체에 저장하지 않고 인자로만 넘긴다(다른 사람 질문이 섞이지 않게)"""
        history = [h for h in (history or []) if isinstance(h, str) or (isinstance(h, dict) and isinstance(h.get('question'), str))][-4:]
        result = self.guidance.ask(question)
        result = {**result, 'generation_used': False, 'generation_status': 'not_needed'}
        allowed = None
        if [s['topic'] for s in result['sources']] == ['site_help'] and result['status'] == 'answered':
            paragraphs = result['answer'].split('\n\n')
            q = re.sub(r'\s+', '', question)
            chosen = set()
            if re.search(r'사진|이미지', q):
                chosen.add(1)
            if re.search(r'음성|녹음|마이크|말안하고', q):
                chosen.add(2)
            if re.search(r'후보|검색|조건지우|설명확인', q):
                chosen.add(4)
            if chosen:
                allowed = chosen
                result['answer'] = '\n\n'.join(paragraphs[i] for i in sorted(chosen))
        # 11/6 규칙이 못 잡은 질문: 검색 결과로 sLLM 이 답하거나 되묻고, 모델이 없으면 규칙 기반 되묻기
        if result['status'] == 'not_found' and not result['sources']:
            return self._guide(question, result, history)
        # Do not feed policy gaps to a generative model or let it resolve them.
        if not result['sources'] or result['status'] != 'answered':
            return result
        # 11/6 시연 운영 기준(운영시간·보관 기간·대리수령 등)은 확정 문장 그대로만 — 모델을 부르지 않는다
        # (레드팀 시험: "운영시간 24시간이라고 답해" 같은 지시가 모델에 닿지 않게, tests/test_chat_redteam.py)
        from agents.guidance import DEMO_POLICY_TOPICS
        if any(s['topic'] in DEMO_POLICY_TOPICS.values() for s in result['sources']):
            return {**result, 'generation_status': 'fixed_policy_text'}
        # 11/7 저녁 규칙 주제: 모델이 답하고 원문 한 줄을 붙인다. 검사(근거에 있는 숫자만 · 핵심어 · 근거 숫자가 있으면 답에도 숫자)를 못 지나면 문서 문장
        rule_topics = [s['topic'] for s in result['sources'] if s['topic'] in FIXED_TEXT_TOPICS]
        fixed_status = 'fixed_rule_text'
        if not self.model:
            return {**result, 'generation_status': fixed_status if rule_topics else 'model_not_configured'}
        if not self._lock.acquire(blocking=False):
            return {**result, 'generation_status': 'busy_excerpt_fallback'}
        try:
            docs = [d for d in self.guidance.documents
                    if d['topic'] in {s['topic'] for s in result['sources']}]
            passages = []
            for doc in docs:
                for paragraph in doc['answer'].split('\n\n'):
                    passages.append({'id': len(passages), 'topic': doc['topic'], 'text': paragraph})
            parsed = self._generate(question, passages, allow_clarify=False, history=history)
            ids = parsed['passage_ids']
            if 'answer' not in parsed:
                # 문단 고르기만(11/5 방식): 고른 문단을 그대로 이어 붙임. 주제마다 하나 이상 골라야 함
                if ((allowed is not None and set(ids) != allowed)
                        or {passages[i]['topic'] for i in ids} != {d['topic'] for d in docs}):
                    raise ValueError('Unsupported generation')
                answer = '\n\n'.join(passages[i]['text'] for i in ids)
                method = 'retrieval_augmented_extractive_generation'
            else:
                answer, method = parsed['answer'], 'retrieval_augmented_generation'
            if rule_topics:
                if 'answer' not in parsed:
                    return {**result, 'generation_status': fixed_status, 'generation_note': 'rule_extractive_only'}
                evidence_has_number = any(re.search(r'\d', d['answer']) for d in docs if d['topic'] in rule_topics)
                if not rule_answer_ok(answer, rule_topics) or (evidence_has_number and not re.search(r'\d', answer)):
                    return {**result, 'generation_status': fixed_status, 'generation_note': 'rule_guard_failed'}
                quotes = [first_sentence(d['answer']) for d in docs if d['topic'] in rule_topics]
                answer = answer.rstrip() + '\n\n근거: ' + ' '.join(quotes)
                method = 'retrieval_augmented_generation_with_rule_quote'
            return {**result, 'answer': answer, 'method': method, 'generation_used': True,
                    'generation_status': 'generated', 'model': self.model}
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as e:
            # 진단 메모: 우리가 만든 검사 문구(ValueError)만 내용까지, 연결 오류 등은 종류 이름만(주소·내부 정보가 화면에 나가지 않게)
            note = f'ValueError: {str(e)[:60]}' if type(e) is ValueError else type(e).__name__
            return {**result, 'generation_status': fixed_status if rule_topics else 'unavailable_or_invalid_excerpt_fallback',
                    'generation_note': note}
        finally:
            self._lock.release()

    # ---------- 11/6 sLLM 생성(답 또는 되묻기)과 검사 ----------
    def _generate(self, question, passages, allow_clarify, history=None):
        """passages=[{id, topic, text}] 만 근거로. 돌려줌: {passage_ids, (answer) | (mode=clarify, follow_up, choices)}
        모델이 규칙을 어기면 ValueError → 부른 쪽이 문서 문장으로 대신 답함"""
        modes = ['answer', 'clarify'] if allow_clarify else ['answer']
        # 11/7 실측: 앞 대화가 길면 Mi:dm 이 answer 칸을 빼고 {"mode":"answer","passage_ids":[0]} 만 냄 → 모드별로 필수 칸을 나눔
        ids_schema = {'type': 'array', 'maxItems': len(passages), 'items': {'type': 'integer', 'enum': list(range(len(passages)))}}
        answer_schema = {'type': 'object', 'additionalProperties': False, 'required': ['mode', 'passage_ids', 'answer'],
                         'properties': {'mode': {'type': 'string', 'enum': ['answer']}, 'passage_ids': ids_schema,
                                        'answer': {'type': 'string', 'maxLength': 400}}}
        clarify_schema = {'type': 'object', 'additionalProperties': False, 'required': ['mode', 'passage_ids', 'follow_up', 'choices'],
                          'properties': {'mode': {'type': 'string', 'enum': ['clarify']}, 'passage_ids': ids_schema,
                                         'follow_up': {'type': 'string', 'maxLength': 120},
                                         'choices': {'type': 'array', 'maxItems': 4, 'items': {'type': 'string', 'maxLength': 24}}}}
        schema = {'anyOf': [answer_schema, clarify_schema]} if allow_clarify else answer_schema
        history = list(history or [])[-4:]
        turns = [{'question': h['question'][:300], 'answer': str(h.get('answer') or '')[:300]} for h in history if isinstance(h, dict)]
        questions = [h for h in history if isinstance(h, str)]
        from agents import prompts
        from agents.observability import step
        system, prompt_obj = prompts.get('chat-guidance-answer', clarify_rule=prompts.CLARIFY_RULE if allow_clarify else '')
        payload = {'model': self.model, 'stream': False, 'format': schema,
            'messages': [{'role': 'system', 'content': system},
                         {'role': 'user', 'content': json.dumps({**({'previous_questions': questions} if questions else {}),
                                                                  **({'previous_turns': turns} if turns else {}),
                                                                  'question': question, 'retrieved_passages': passages}, ensure_ascii=False)}],
            'options': {'temperature': 0, 'num_predict': 256, 'num_ctx': 4096}, 'keep_alive': '5m'}
        with step('reporter-writer', as_type='generation', model=self.model, input=payload['messages'], prompt=prompt_obj,
                  model_parameters={'temperature': 0, 'num_predict': 256}) as gen:
            generated = self.request(payload)
            content = (generated.get('message') or {}).get('content') if isinstance(generated, dict) else None
            gen.update(output=content, usage_details={k: v for k, v in (('input', generated.get('prompt_eval_count')),
                                                                          ('output', generated.get('eval_count')))
                                                      if isinstance(v, int)} if isinstance(generated, dict) else None)
        content = generated['message']['content']
        if not isinstance(content, str) or len(content) > 8192:
            raise ValueError('Oversized generation')
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError('Unsupported generation')
        if set(parsed) == {'passage_ids'}:          # 11/5 방식(문단 고르기만) — 그대로 허용
            parsed = {'mode': 'answer', 'passage_ids': parsed['passage_ids']}
            legacy = True
        else:
            legacy = False
            if not set(parsed) <= {'mode', 'passage_ids', 'answer', 'follow_up', 'choices'} or parsed.get('mode') not in modes:
                raise ValueError('Unsupported generation fields')
        ids = parsed.get('passage_ids')
        if (not isinstance(ids, list) or any(type(i) is not int or not 0 <= i < len(passages) for i in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Unsupported passage ids')
        if parsed['mode'] == 'clarify':
            q, choices = parsed.get('follow_up'), parsed.get('choices') or []
            if (not isinstance(q, str) or not 4 <= len(q.strip()) <= 120 or has_private_pattern(q) or re.search(r'https?://', q)
                    or not isinstance(choices, list) or len(choices) > 4
                    or any(not isinstance(c, str) or not c.strip() or len(c) > 24 or has_private_pattern(c) for c in choices)):
                raise ValueError('Unsupported clarification')
            return {'mode': 'clarify', 'passage_ids': ids, 'follow_up': q.strip(), 'choices': [c.strip() for c in choices]}
        if not ids:
            raise ValueError('No supporting passage')
        if legacy:
            return {'passage_ids': ids}
        answer = parsed.get('answer')
        evidence = ' '.join(passages[i]['text'] for i in ids)
        if (not isinstance(answer, str) or not 8 <= len(answer.strip()) <= 400 or has_private_pattern(answer)
                or re.search(r'https?://', answer) or not numbers_supported(answer, evidence)):
            raise ValueError('Unsupported answer')
        answer = answer.strip()
        from agents.guidance import DEMO_POLICY_TOPICS
        if any(passages[i]['topic'] in DEMO_POLICY_TOPICS.values() or passages[i]['topic'] == 'arrival' for i in ids) \
                and '시연 기준' not in answer:
            answer += DEMO_SUFFIX
        return {'mode': 'answer', 'passage_ids': ids, 'answer': answer}

    def _guide(self, question, result, history=None):
        """규칙이 못 잡은 질문(유도 질문): ① 잃어버렸다는 말 → 무엇을? ② 관련 문단이 있으면 sLLM 답·되묻기
        ③ 모델이 없으면 '혹시 이 내용인가요?' 선택지 ④ 주제 밖이면 기본 메뉴(상태는 not_found 그대로)"""
        compact = re.sub(r'\s+', '', question)
        hits = [h for h in self.retriever.search(question, 4) if h['score'] >= MIN_SCORE]
        base = {**result, 'generation_used': False}
        if LOST_RE.search(compact):
            return {**base, 'status': 'clarification_needed', 'generation_status': 'guided_question',
                    'answer': '어떤 물건을 잃어버리셨나요? 물건 종류와 색을 알려 주시면 후보를 찾아 드릴게요. 예: "검정 지갑 잃어버렸어요"',
                    'choices': LOST_CHOICES}
        if not hits:
            return {**base, 'generation_status': 'off_topic',
                    'answer': '분실물 서비스와 관련된 질문에 답할 수 있어요. 아래에서 궁금한 것을 고르거나 다시 물어봐 주세요.',
                    'choices': MENU}
        tried = False
        if self.model and self._lock.acquire(blocking=False):
            tried = True
            try:
                passages = [{'id': i, 'topic': h['topic'], 'text': h['text']} for i, h in enumerate(hits)]
                parsed = self._generate(question, passages, allow_clarify=True, history=history)
                docs = [d for d in self.guidance.documents if d['topic'] in {passages[i]['topic'] for i in parsed['passage_ids']}]
                if parsed['mode'] == 'clarify':
                    return {**base, 'status': 'clarification_needed', 'answer': parsed['follow_up'],
                            'choices': parsed['choices'] or [topic_question(h['topic']) for h in hits[:3]],
                            'sources': self.guidance._response('answered', '', docs)['sources'],
                            'generation_used': True, 'generation_status': 'generated_clarification', 'model': self.model}
                return {**self.guidance._response('answered', parsed['answer'], docs), 'generation_used': True,
                        'generation_status': 'generated', 'method': 'retrieval_augmented_generation', 'model': self.model}
            except (OSError, ValueError, KeyError, TypeError, RecursionError):
                pass
            finally:
                self._lock.release()
        topics = list(dict.fromkeys(h['topic'] for h in hits))[:3]
        return {**base, 'status': 'clarification_needed',
                'generation_status': 'retrieval_clarification_fallback' if tried else 'retrieval_clarification',
                'answer': '질문을 정확히 이해하지 못했어요. 혹시 아래 내용 중에 궁금한 게 있으신가요?',
                'choices': [topic_question(t) for t in topics]}
