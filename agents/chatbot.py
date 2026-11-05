"""LF-5 LangGraph orchestration of document guidance and read-only item search."""
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
    search_context: dict
    route: str
    result: dict


class Chatbot:
    def __init__(self, guidance, rag=None, search=None):
        from langgraph.graph import StateGraph, START, END
        self.guidance = guidance
        self.rag = rag or GroundedRag(guidance)
        self.search = search or SearchAgent()
        graph = StateGraph(ChatState)
        graph.add_node('route_question', self._route)
        graph.add_node('document_guidance', lambda s: {'result': self.rag.ask(s['question'])})
        graph.add_node('item_search', lambda s: {'result': self.search.ask(s['question'], _search_access.get(), s.get('search_context'))})
        graph.add_node('combined_help', self._both)
        graph.add_edge(START, 'route_question')
        graph.add_conditional_edges('route_question', lambda s: s['route'],
                                    {'guidance': 'document_guidance', 'search': 'item_search', 'both': 'combined_help'})
        graph.add_edge('document_guidance', END)
        graph.add_edge('item_search', END)
        graph.add_edge('combined_help', END)
        self.graph = graph.compile()

    @staticmethod
    def _route(state):
        q = unicodedata.normalize('NFKC', natural_question(state['question'])).lower()
        q = re.sub(r'[\s\u200b-\u200d\ufeff]', '', q)
        # Process/help questions stay in guidance, even when they mention searching.
        help_question = re.search(r'방법|절차|사용법|이용법|어떻게|운영|개인정보|보관기간|인증|동의|예약|준비물|수령|주말|몇시|보관', q) or re.search(r'후보가뭐|후보.*(?:뜻|의미|확정)', q)  # 11/5: 후보의 뜻을 묻는 질문은 안내로
        search = re.search(r'찾아|검색|후보|접수번호|(?:지갑|휴대폰|핸드폰|usb|립밤|보조배터리|핸드크림).*(?:있나요|있어|있나|있니|있습니까)', q)
        direct_search = search_intent(q)
        if help_question and direct_search:
            return {'route': 'both'}
        return {'route': 'search' if (search or direct_search) and not help_question else 'guidance'}

    def _both(self, state):
        guide = self.rag.ask(state['question'])
        search = self.search.ask(state['question'], _search_access.get(), state.get('search_context'))
        return {'result': {**search, 'answer': guide['answer'] + '\n\n' + search['answer'],
                           'sources': guide['sources'], 'generation_used': guide.get('generation_used', False),
                           'status': 'answered' if guide['status'] == 'answered' and search['item_search_performed'] else 'partial',
                           'method': 'document_guidance_and_read_only_item_search'}}

    def ask(self, question, access_token=None, context=None, history=None):
        question = checked_text(question, '질문', 500)
        context = checked_context(context)
        history = checked_history(history)
        question, context, resolved = resolve_turn(question, history, context, self.guidance)
        if resolved is None:
            return {**self.guidance._response('clarification_needed',
                '어떤 내용을 이어서 물으신 건가요? 찾는 물건·색상이나 궁금한 절차를 함께 적어주세요. 예: 파란 지갑 찾아줘 / 본인인증에 실패하면?', []),
                'agent': 'guidance', 'context_used': False}
        # Bearer credentials must never enter graph state, checkpoints or tracing.
        context_token = _search_access.set(access_token)
        try:
            with tracing_context(enabled=False, parent=False):
                state = self.graph.invoke({'question': question, 'search_context': context}, config={'callbacks': []})
        finally:
            _search_access.reset(context_token)
        return {**state['result'], 'agent': state['route'],
                'context_used': resolved,
                'orchestration': 'langgraph_guidance_and_item_search'}

    def inspect_matching(self, question, report, inspector=None):
        """Internal LF-20 check only. Not exposed by the chat HTTP routes."""
        from agents.matching_inspection import MatchingInspection
        return (inspector or MatchingInspection()).ask(question, report)

    def inspect_inventory_matching(self, question, scene, inventory_check, inspector=None):
        """Internal scene/receipt-link inspection. No HTTP or real DB wiring."""
        from agents.matching_inspection import MatchingInspection
        return (inspector or MatchingInspection()).ask_bound(question, scene, inventory_check)
