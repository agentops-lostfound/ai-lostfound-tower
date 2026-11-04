"""LF-5 LangGraph orchestration of document guidance and read-only item search."""
import re
import unicodedata
from contextvars import ContextVar
from typing import TypedDict
from agents.lost_input import checked_text
from agents.chat_rag import GroundedRag
from agents.chat_search import SearchAgent
from langsmith import tracing_context

_search_access = ContextVar('lf_chat_search_access', default=None)


class ChatState(TypedDict, total=False):
    question: str
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
        graph.add_node('item_search', lambda s: {'result': self.search.ask(s['question'], _search_access.get())})
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
        q = unicodedata.normalize('NFKC', state['question']).lower()
        q = re.sub(r'[\s\u200b-\u200d\ufeff]', '', q)
        # Process/help questions stay in guidance, even when they mention searching.
        help_question = re.search(r'방법|절차|사용법|이용법|어떻게|운영|개인정보|보관기간|인증|동의|예약', q)
        search = re.search(r'찾아|검색|후보|접수번호|(?:지갑|휴대폰|핸드폰|usb|립밤|보조배터리|핸드크림).*(?:있나요|있어|있나|있니|있습니까)', q)
        direct_search = re.search(r'찾아줘|찾아주세요|검색해줘|검색해주세요|후보.*보여', q)
        if help_question and direct_search:
            return {'route': 'both'}
        return {'route': 'search' if search and not help_question else 'guidance'}

    def _both(self, state):
        guide = self.rag.ask(state['question'])
        search = self.search.ask(state['question'], _search_access.get())
        return {'result': {**search, 'answer': guide['answer'] + '\n\n' + search['answer'],
                           'sources': guide['sources'], 'generation_used': guide.get('generation_used', False),
                           'status': 'answered' if guide['status'] == 'answered' and search['item_search_performed'] else 'partial',
                           'method': 'document_guidance_and_read_only_item_search'}}

    def ask(self, question, access_token=None):
        question = checked_text(question, '질문', 500)
        # Bearer credentials must never enter graph state, checkpoints or tracing.
        context_token = _search_access.set(access_token)
        try:
            with tracing_context(enabled=False, parent=False):
                state = self.graph.invoke({'question': question}, config={'callbacks': []})
        finally:
            _search_access.reset(context_token)
        return {**state['result'], 'agent': state['route'],
                'orchestration': 'langgraph_guidance_and_item_search'}
