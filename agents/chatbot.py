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
from agents.chat_search import SearchAgent
from agents.search_context import checked_context
from agents.chat_conversation import checked_history, natural_question, resolve_turn, search_intent
from langsmith import tracing_context

_search_access = ContextVar('lf_chat_search_access', default=None)


class ChatState(TypedDict, total=False):
    question: str
    history: list
    search_context: dict
    ops_turn: bool
    route: str
    result: dict


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
    def __init__(self, guidance, rag=None, search=None, ops=None):
        from langgraph.graph import StateGraph, START, END
        self.guidance = guidance
        self.rag = rag or GroundedRag(guidance)
        self.search = search or SearchAgent()
        self.ops = ops          # 관제 분석 에이전트(run(question) → {"report", ...}). 없으면 직원 관제 길은 닫힘
        graph = StateGraph(ChatState)
        graph.add_node('route_question', self._route)
        graph.add_node('document_guidance', lambda s: {'result': self._rag_ask(s)})
        graph.add_node('item_search', lambda s: {'result': self.search.ask(s['question'], _search_access.get(), s.get('search_context'))})
        graph.add_node('combined_help', self._both)
        graph.add_node('ops_report', self._ops)
        graph.add_edge(START, 'route_question')
        graph.add_conditional_edges('route_question', lambda s: s['route'],
                                    {'guidance': 'document_guidance', 'search': 'item_search', 'both': 'combined_help',
                                     'ops': 'ops_report'})
        graph.add_edge('ops_report', END)
        graph.add_edge('document_guidance', END)
        graph.add_edge('item_search', END)
        graph.add_edge('combined_help', END)
        self.graph = graph.compile()

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
        if help_question and direct_search:
            return {'route': 'both'}
        return {'route': 'search' if (search or direct_search) and not help_question else 'guidance'}

    def _both(self, state):
        guide = self._rag_ask(state)
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

    def ask(self, question, access_token=None, context=None, history=None, staff=False):
        question = checked_text(question, '질문', 500)
        context = checked_context(context)
        history = checked_history(history)
        ops_turn = bool(staff and self.ops is not None and is_ops_question(question))
        if ops_turn:            # 관제 질문은 앞 대화와 합치지 않고 그대로 분석한다
            resolved = False
        else:
            question, context, resolved = resolve_turn(question, history, context, self.guidance)
        if resolved is None:
            return {**self.guidance._response('clarification_needed',
                '어떤 내용을 이어서 물으신 건가요? 찾는 물건·색상이나 궁금한 절차를 함께 적어주세요. 예: 파란 지갑 찾아줘 / 본인인증에 실패하면?', []),
                'agent': 'guidance', 'context_used': False}
        # Bearer credentials must never enter graph state, checkpoints or tracing.
        context_token = _search_access.set(access_token)
        try:
            with tracing_context(enabled=False, parent=False):
                state = self.graph.invoke({'question': question, 'search_context': context, 'ops_turn': ops_turn,
                                           'history': history},
                                          config={'callbacks': []})
        finally:
            _search_access.reset(context_token)
        return {**state['result'], 'agent': state['route'],
                'context_used': resolved,
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
