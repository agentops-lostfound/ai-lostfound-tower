"""LF-5 LangGraph orchestration of document guidance and read-only item search."""
import re
import unicodedata
from contextvars import ContextVar
from typing import TypedDict
from agents.lost_input import checked_text
from agents.chat_rag import GroundedRag
from agents.chat_search import SearchAgent
from agents.search_context import checked_context
from agents.chat_conversation import checked_history, natural_question, resolve_turn, search_intent, brief_reaction
from langsmith import tracing_context
from agents.chat_communication import ConversationInterpreter, scope_violation, communication_response
from agents.chat_dialogue import dialogue_response
from agents.chat_search_turns import prepare_search_turn

_search_access = ContextVar('lf_chat_search_access', default=None)


class ChatState(TypedDict, total=False):
    question: str
    search_context: dict
    route: str
    result: dict
    semantic_topics: list
    planned_route: str


class Chatbot:
    def __init__(self, guidance, rag=None, search=None, interpreter=None):
        from langgraph.graph import StateGraph, START, END
        self.guidance = guidance
        self.rag = rag or GroundedRag(guidance)
        self.search = search or SearchAgent()
        self.interpreter = interpreter or ConversationInterpreter(guidance, model=self.rag.model,
                                                                 request=getattr(self.rag, 'intent_request', None),
                                                                 lock=getattr(self.rag, '_lock', None))
        graph = StateGraph(ChatState)
        graph.add_node('route_question', self._route)
        graph.add_node('document_guidance', lambda s: {'result': self.rag.ask(s['question'], topics=s.get('semantic_topics'))})
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
        if state.get('planned_route'):
            return {'route': state['planned_route']}
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
                           'generation_status': guide.get('generation_status', 'not_needed'),
                           **({'model': guide['model']} if guide.get('generation_used') and guide.get('model') else {}),
                           'guidance_status': guide['status'], 'search_status': search['status'],
                           'status': 'answered' if guide['status'] == 'answered' and search['item_search_performed'] else 'partial',
                           'method': 'document_guidance_and_read_only_item_search'}}

    def ask(self, question, access_token=None, context=None, history=None):
        question = checked_text(question, '질문', 500)
        context = checked_context(context)
        history = checked_history(history)
        violation = scope_violation(question)
        if violation:
            return communication_response(self.guidance, 'restricted' if violation == 'restricted' else 'unsupported')
        correction = prepare_search_turn(self.guidance, question, history, context)
        if correction:
            if correction.get('response'):
                return {**correction['response'], 'semantic_interpretation_used': False}
            question, context, history = correction['question'], correction['context'], []
        dialogue = dialogue_response(self.guidance, question, history)
        if dialogue is not None:
            return {**dialogue, 'semantic_interpretation_used': False}
        reaction = brief_reaction(question)
        if reaction:
            previous = next((turn for turn in reversed(history) if not brief_reaction(turn)), '')
            search_context_used = bool(context or previous and search_intent(previous))
            result = communication_response(self.guidance, reaction, question)
            if reaction == 'disappointment' and search_context_used:
                result['answer'] = '아쉽네요. 원하시면 입력한 물건·색상이 맞는지 다시 확인해볼 수 있어요. 조건은 말씀해주실 때만 바꿀게요.'
            return {**result, 'context_used': bool(history or context), 'semantic_interpretation_used': False}
        question, context, resolved = resolve_turn(question, history, context, self.guidance)
        plan = None
        baseline = self.guidance.ask(question)
        uncertain_scope = (baseline['status'] == 'policy_pending' and not re.search(
            r'분실|물건|지갑|휴대폰|usb|센터|키오스크|사이트|수령|인증|동의|개인정보|운영|보관|신분|습득|택배|배송|우편|대리|대신|수수료|비용', question.lower()))
        # A mentioned lost item does not turn an unrelated command into a search.
        unrelated_command = bool(re.search(r'지어|써줘|작성해|만들어|요약해|추천해|번역해|풀어줘', question))
        orphan = not history and not context and bool(re.fullmatch(
            r'(?:그거|그건|그걸)(?:\s*(?:어떻게|왜|못하면|안되면|실패하면))?[?？.!\s]*', question))
        if orphan:
            return communication_response(self.guidance, 'clarification')
        if (((resolved is None or self._route({'question': question})['route'] == 'guidance')
                and (baseline['status'] == 'not_found' or uncertain_scope))
                or (unrelated_command and baseline['status'] == 'not_found')):
            plan = self.interpreter.interpret(question, history)
        if plan and plan['kind'] not in ('guidance', 'search'):
            return {**communication_response(self.guidance, plan['kind'], question), 'semantic_interpretation_used': True}
        if resolved is None:
            if plan:
                resolved = bool(history)
            else:
                return {**self.guidance._response('clarification_needed',
                    '어떤 내용을 이어서 물으신 건가요? 찾는 물건·색상이나 궁금한 절차를 함께 적어주세요. 예: 파란 지갑 찾아줘 / 본인인증에 실패하면?', []),
                    'agent': 'guidance', 'context_used': False}
        # Bearer credentials must never enter graph state, checkpoints or tracing.
        context_token = _search_access.set(access_token)
        try:
            with tracing_context(enabled=False, parent=False):
                initial = {'question': question, 'search_context': context}
                if plan:
                    initial.update(planned_route='guidance' if plan['kind'] == 'guidance' else 'search',
                                   semantic_topics=plan['topics'])
                state = self.graph.invoke(initial, config={'callbacks': []})
        finally:
            _search_access.reset(context_token)
        return {**state['result'], 'agent': state['route'],
                'semantic_interpretation_used': bool(plan),
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
