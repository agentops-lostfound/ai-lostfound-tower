"""LF-5 LangGraph orchestration of document guidance and read-only item search.

11/6 변재원: 직원 화면(관리자 로그인)에서만 열리는 네 번째 길 `ops_report` 를 더했다.
"오늘 반환 실패 원인 알려줘" 같은 관제 질문을 LangManus 구조 관제 분석 에이전트(agents/ops_analyst.py)로 보낸다.
분실인 화면에는 이 길이 없다(staff=True 는 chat_api 가 관리자 로그인을 확인한 뒤에만 넘긴다).
"""
import re
import unicodedata
from contextvars import ContextVar
from typing import TypedDict
from agents.lost_input import checked_text
from agents.chat_rag import GroundedRag
from agents.chat_progress import notify
from agents.chat_search import SearchAgent
from agents.search_context import checked_context
from agents.chat_conversation import checked_history, checked_turns, natural_question, resolve_turn, search_intent
from langsmith import tracing_context

_search_access = ContextVar('lf_chat_search_access', default=None)


class ChatState(TypedDict, total=False):
    question: str
    history: list
    search_context: dict
    ops_turn: bool
    route: str
    result: dict
    # 11/7 DeerFlow 구조: coordinator → planner → supervisor ⇄ 일꾼 → reporter
    intent: str          # coordinator 판단(service·greeting·thanks·off_topic)
    plan: list           # planner 가 고른 일꾼 순서(guidance·item_search·ops)
    results: dict        # 일꾼별 결과
    path: list           # 지나간 에이전트(trace·화면 확인용)
    questions: list      # 앞 질문 글만(coordinator·planner 모델 맥락)
    routing: str         # model(모델이 판단) · rule(규칙으로 대체)
    next: str            # supervisor 가 고른 다음 칸


# 직원 관제 질문: 기록을 세고 원인을 찾는 말(STRONG)이 있거나, 문제 낱말 + 기간 낱말이 같이 있을 때만.
# "본인인증 실패하면?"·"반환 절차 알려줘" 같은 이용 안내 질문은 직원이 물어도 안내 길로 간다.
OPS_STRONG = re.compile(r'원인|현황|통계|요약|보고|분석|몇건|건수|경보|처리시간|평균시간|p95|성공률|실패율')
OPS_TOPIC = re.compile(r'실패|보류|거절|느려|오래|로봇|반환|챗봇|집기|정지|알림')
OPS_WHEN = re.compile(r'오늘|어제|최근|이번|지금까지|요즘|방금')
HOW_TO = re.compile(r'방법|절차|어떻게하|하면|사용법|이용법')


def is_ops_question(question):
    q = re.sub(r'[\s\u200b-\u200d\ufeff]', '', unicodedata.normalize('NFKC', question or '').lower())
    if OPS_STRONG.search(q):
        return True
    return bool(OPS_TOPIC.search(q) and OPS_WHEN.search(q) and not HOW_TO.search(q))


def chat_text(report):
    """마크다운 보고서 → 채팅 말풍선용 글(위젯은 글자 그대로 보여 준다): 제목 기호·굵게·기울임 표시를 뺀다."""
    out = []
    for line in report.splitlines():
        line = re.sub(r'^#\s+', '', line)
        line = re.sub(r'^#{2,6}\s+', '■ ', line)
        line = line.replace('**', '')
        line = re.sub(r'^_(.+)_$', r'\1', line.strip()) if line.strip().startswith('_') else line
        out.append(line)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip()


class Chatbot:
    def __init__(self, guidance, rag=None, search=None, ops=None, brain=None):
        """brain: coordinator·planner 를 맡을 모델(agents/chat_agents.AgentBrain). 없으면 같은 칸을 규칙으로 처리"""
        from langgraph.graph import StateGraph, START, END
        self.guidance = guidance
        self.rag = rag or GroundedRag(guidance)
        self.search = search or SearchAgent()
        self.ops = ops          # 관제 분석 에이전트(run(question) → {"report", ...}). 없으면 직원 관제 길은 닫힘
        self.brain = brain
        graph = StateGraph(ChatState)
        graph.add_node('coordinator', self._coordinator)
        graph.add_node('planner', self._planner)
        graph.add_node('supervisor', self._supervisor)
        graph.add_node('researcher', self._researcher)
        graph.add_node('item_search', self._item_search)
        graph.add_node('ops_analyst', self._ops_worker)
        graph.add_node('reporter', self._reporter)
        graph.add_edge(START, 'coordinator')
        def route_after_coordinator(s):      # 11/8: 이름 있는 함수 → Langfuse 나무에 'RunnableCallable' 대신 이 이름으로 보임
            return 'end' if s.get('result') else 'planner'

        def route_next_worker(s):
            return s['next']
        graph.add_conditional_edges('coordinator', route_after_coordinator, {'end': END, 'planner': 'planner'})
        graph.add_edge('planner', 'supervisor')
        graph.add_conditional_edges('supervisor', route_next_worker,
                                    {'guidance': 'researcher', 'item_search': 'item_search', 'ops': 'ops_analyst',
                                     'reporter': 'reporter'})
        for worker in ('researcher', 'item_search', 'ops_analyst'):
            graph.add_edge(worker, 'supervisor')
        graph.add_edge('reporter', END)
        self.graph = graph.compile()

    # ---------- 11/7 DeerFlow 구조의 칸들 ----------
    def _coordinator(self, state):
        """인사·감사는 정해진 짧은 답으로 끝내고, 나머지는 planner 로. 관제 질문(관리자 확인됨)은 바로 넘김"""
        from agents.chat_agents import GREETING_REPLY, THANKS_REPLY
        from agents.observability import node_step
        with node_step('coordinator', as_type='agent', input={'question': state['question']}) as obs:
            intent, routing = 'service', 'rule'
            if not state.get('ops_turn') and self.brain is not None:
                got = self.brain.coordinate(state['question'], state.get('questions'))
                if got is not None:
                    intent, routing = got[0], ('model' if got[1] else 'rule')
            out = {'intent': intent, 'routing': routing, 'path': ['coordinator']}
            if intent in ('greeting', 'thanks'):
                out['result'] = {**self.guidance._response('answered', GREETING_REPLY if intent == 'greeting' else THANKS_REPLY, []),
                                 'generation_used': False, 'generation_status': 'coordinator_reply'}
                out['route'] = 'coordinator'
            obs.update(output={'intent': intent, 'routing': routing})
            return out

    @staticmethod
    def _signals(state):
        """규칙이 분명하게 찾은 일꾼(planner 가 지울 수 없음)"""
        q = unicodedata.normalize('NFKC', natural_question(state['question'])).lower()
        q = re.sub(r'[\s\u200b-\u200d\ufeff]', '', q)
        help_question = re.search(r'방법|절차|사용법|이용법|어떻게|운영|개인정보|보관기간|인증|동의|예약|준비물|수령|주말|몇시|보관', q) or re.search(r'후보가뭐|후보.*(?:뜻|의미|확정)', q)
        search = re.search(r'찾아|검색|후보|접수번호|(?:지갑|모형폰|휴대폰|핸드폰|usb|립밤|보조배터리|핸드크림).*(?:있나요|있어|있나|있니|있습니까)', q)
        from agents.guidance import off_topic
        if off_topic(q):          # 11/9 서비스 밖 질문은 물건 검색을 강제하지 않음
            return {'guidance': True, 'item_search': False}
        return {'guidance': bool(help_question), 'item_search': bool((search or search_intent(q)) and not help_question) or bool(help_question and search_intent(q))}

    def _planner(self, state):
        from agents.observability import node_step
        with node_step('planner', as_type='agent', input={'question': state['question']}) as obs:
            if state.get('ops_turn'):
                plan, routing = ['ops'], 'rule'
            elif state.get('intent') == 'off_topic':
                plan, routing = ['guidance'], 'model'        # 주제 밖: 안내 길(메뉴 버튼 답)로만 — 물건 검색 안내를 붙이지 않음
            else:
                rule = {'guidance': ['guidance'], 'search': ['item_search'], 'both': ['item_search', 'guidance']}[self._route(state)['route']]
                plan, routing = rule, 'rule'
                if self.brain is not None:
                    sig = self._signals(state)
                    must = [w for w in ('item_search', 'guidance') if sig[w]]
                    got = self.brain.plan(state['question'], state.get('questions'), must)
                    if got:
                        plan, routing = got, 'model'
            obs.update(output={'plan': plan, 'routing': routing})
            return {'plan': plan, 'results': {}, 'path': state.get('path', []) + ['planner'],
                    'routing': 'model' if routing == 'model' or state.get('routing') == 'model' else 'rule'}

    @staticmethod
    def _supervisor(state):
        done = state.get('results') or {}
        nxt = next((w for w in state.get('plan', []) if w not in done), 'reporter')
        return {'next': nxt, 'path': state.get('path', []) + ['supervisor']}

    def _researcher(self, state):
        from agents.observability import node_step
        with node_step('researcher', as_type='retriever', input={'question': state['question']}) as obs:
            res = self._rag_ask(state)
            obs.update(output={'status': res.get('status'), 'generation_status': res.get('generation_status'),
                               'topics': [x.get('topic') for x in res.get('sources', [])], 'answer': res.get('answer', '')[:500]})
        return {'results': {**(state.get('results') or {}), 'guidance': res}, 'path': state.get('path', []) + ['researcher']}

    def _item_search(self, state):
        from agents.observability import node_step
        with node_step('item_search', as_type='tool', input={'question': state['question']}) as obs:
            notify('search')
            res = self.search.ask(state['question'], _search_access.get(), state.get('search_context'))
            obs.update(output={'status': res.get('status'), 'candidates': len(res.get('candidates') or [])})
        return {'results': {**(state.get('results') or {}), 'item_search': res}, 'path': state.get('path', []) + ['item_search']}

    def _ops_worker(self, state):
        notify('analyze')
        from agents.observability import node_step
        with node_step('ops_analyst', as_type='agent', input={'question': state['question']}) as obs:
            res = self._ops(state)['result']
            obs.update(output={'focus': res.get('ops_focus')})
        return {'results': {**(state.get('results') or {}), 'ops': res}, 'path': state.get('path', []) + ['ops_analyst']}

    def _reporter(self, state):
        """일꾼 결과를 화면에 낼 답 하나로(두 개면 기존 combined 방식: 안내 → 검색 순)"""
        r = state.get('results') or {}
        if 'ops' in r:
            return {'result': r['ops'], 'route': 'ops', 'path': state.get('path', []) + ['reporter']}
        if 'guidance' in r and 'item_search' in r:
            guide, search = r['guidance'], r['item_search']
            result = {**search, 'answer': guide['answer'] + '\n\n' + search['answer'],
                      'sources': guide['sources'], 'generation_used': guide.get('generation_used', False),
                      'generation_status': guide.get('generation_status'), 'generation_note': guide.get('generation_note'),
                      'status': 'answered' if guide['status'] == 'answered' and search['item_search_performed'] else 'partial',
                      'method': 'document_guidance_and_read_only_item_search'}
            route = 'both'
        elif 'item_search' in r:
            result, route = r['item_search'], 'search'
        else:
            result, route = r.get('guidance') or self._rag_ask(state), 'guidance'
        return {'result': result, 'route': route, 'path': state.get('path', []) + ['reporter']}

    @staticmethod
    def _route(state):
        if state.get('ops_turn'):
            return {'route': 'ops'}
        q = unicodedata.normalize('NFKC', natural_question(state['question'])).lower()
        q = re.sub(r'[\s\u200b-\u200d\ufeff]', '', q)
        # Process/help questions stay in guidance, even when they mention searching.
        help_question = re.search(r'방법|절차|사용법|이용법|어떻게|운영|개인정보|보관기간|인증|동의|예약|준비물|수령|주말|몇시|보관', q) or re.search(r'후보가뭐|후보.*(?:뜻|의미|확정)', q)  # 11/5: 후보의 뜻을 묻는 질문은 안내로
        search = re.search(r'찾아|검색|후보|접수번호|(?:지갑|모형폰|휴대폰|핸드폰|usb|립밤|보조배터리|핸드크림).*(?:있나요|있어|있나|있니|있습니까)', q)
        direct_search = search_intent(q)
        from agents.guidance import off_topic
        if off_topic(q):          # 11/9 "맛집 찾아줘" 가 '찾아' 때문에 물건 검색으로 가던 것 → 안내 길(정해진 문장)
            return {'route': 'guidance'}
        if help_question and direct_search:
            return {'route': 'both'}
        return {'route': 'search' if (search or direct_search) and not help_question else 'guidance'}

    def _both(self, state):
        guide = self._rag_ask(state)
        notify('search')
        search = self.search.ask(state['question'], _search_access.get(), state.get('search_context'))
        return {'result': {**search, 'answer': guide['answer'] + '\n\n' + search['answer'],
                           'sources': guide['sources'], 'generation_used': guide.get('generation_used', False),
                           'status': 'answered' if guide['status'] == 'answered' and search['item_search_performed'] else 'partial',
                           'method': 'document_guidance_and_read_only_item_search'}}

    def _rag_ask(self, state):
        """11/6: 이전 질문(사용자 말만)을 sLLM 에 맥락으로 넘긴다. history 를 받지 않는 예전 rag 부품도 그대로 동작"""
        history = state.get('history') or []
        return self.rag.ask(state['question'], history=history) if history else self.rag.ask(state['question'])

    def _ops(self, state):
        """직원 관제 질문 → LangManus 구조 에이전트(조정→계획→감독⇄조사·분석·보고). 숫자는 관제 기록에서만."""
        try:
            out = self.ops.run(state['question'])
        except Exception:      # 에이전트 오류 문구는 화면에 내보내지 않는다
            out = {'report': '관제 분석을 끝내지 못했습니다. 관제탑 상태를 확인한 뒤 다시 물어봐 주세요.', 'accepted': False}
        report = chat_text(out.get('report') or '') or '관제 분석 결과가 비어 있습니다. 질문을 바꿔 다시 물어봐 주세요.'
        return {'result': {'status': 'answered' if out.get('accepted') and out.get('facts') else 'partial',
                           'answer': report, 'sources': [], 'candidates': [],
                           'scope': '관제탑 기록 분석 · 직원 전용',
                           'method': 'langmanus_style_ops_agents',
                           'ops_focus': out.get('focus'), 'ops_used_llm': list(out.get('used_llm') or []),
                           'generation_used': bool(out.get('used_llm')),
                           'generation_status': 'ops_report',
                           'item_search_performed': False}}

    def ask(self, question, access_token=None, context=None, history=None, staff=False, session_id=None, channel='web'):
        """session_id: 같은 화면 대화를 Langfuse 에서 묶는 번호(화면이 만든 무작위 값, 개인정보 아님). channel: web·kiosk·staff"""
        from agents.observability import conversation, step
        with conversation(session_id=session_id, tags=[channel]):
            with step('lost-found-chatbot', as_type='chain', input={'question': question}) as root:
                out = self._ask(question, access_token, context, history, staff)
                root.update(output={'answer': out.get('answer', '')[:800], 'agent': out.get('agent'),
                                    'path': out.get('agent_path'), 'routing': out.get('routing'),
                                    'generation_status': out.get('generation_status')})
                return out

    def _ask(self, question, access_token=None, context=None, history=None, staff=False):
        question = checked_text(question, '질문', 500)
        context = checked_context(context)
        turns = checked_turns(history)          # 11/7 앞 질문 + 챗봇 답(모델 맥락용)
        history = checked_history(history)
        ops_turn = bool(staff and self.ops is not None and is_ops_question(question))
        if ops_turn:            # 관제 질문은 앞 대화와 합치지 않고 그대로 분석한다
            resolved = False
        else:
            question, context, resolved = resolve_turn(question, history, context, self.guidance)
        if resolved is None and self.brain is not None:
            resolved = False        # 11/7: 무엇을 가리키는지 규칙이 못 정하면 모델(planner·안내 작성)이 앞 대화를 보고 판단
        if resolved is None:
            return {**self.guidance._response('clarification_needed',
                '어떤 내용을 이어서 물으신 건가요? 찾는 물건·색상이나 궁금한 절차를 함께 적어주세요. 예: 파란 지갑 찾아줘 / 본인인증에 실패하면?', []),
                'agent': 'guidance', 'context_used': False}
        # Bearer credentials must never enter graph state, checkpoints or tracing.
        context_token = _search_access.set(access_token)
        try:
            from agents.observability import callbacks_active, graph_callbacks
            handlers = graph_callbacks()     # 11/7 Langfuse callback 방식: 그래프 칸별 기록(키 없으면 빈 목록 = 기록 안 함)
            # 접속 토큰은 contextvar 에만 있어 그래프 상태·기록에 들어가지 않는다(LangSmith 기록은 계속 끔)
            with tracing_context(enabled=False, parent=False), callbacks_active(bool(handlers)):
                state = self.graph.invoke({'question': question, 'search_context': context, 'ops_turn': ops_turn,
                                           'history': turns if turns else history, 'questions': history},
                                          config={'callbacks': handlers, 'run_name': 'chatbot-graph'})
        finally:
            _search_access.reset(context_token)
        return {**state['result'], 'agent': state['route'],
                'agent_path': state.get('path', []), 'routing': state.get('routing', 'rule'),
                'context_used': bool(resolved),
                'orchestration': 'langgraph_guidance_item_search_and_staff_ops' if self.ops is not None
                                 else 'langgraph_guidance_and_item_search'}

    def inspect_matching(self, question, report, inspector=None):
        """Internal LF-20 check only. Not exposed by the chat HTTP routes."""
        from agents.matching_inspection import MatchingInspection
        return (inspector or MatchingInspection()).ask(question, report)

    def inspect_inventory_matching(self, question, scene, inventory_check, inspector=None):
        """Internal scene/receipt-link inspection. No HTTP or real DB wiring."""
        from agents.matching_inspection import MatchingInspection
        return (inspector or MatchingInspection()).ask_bound(question, scene, inventory_check)
