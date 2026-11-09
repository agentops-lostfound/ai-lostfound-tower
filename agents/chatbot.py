"""LF-5 LangGraph orchestration of document guidance and read-only item search.

11/6 변재원: 직원 화면(관리자 로그인)에서만 열리는 네 번째 길 `ops_report` 를 더했다.
"오늘 반환 실패 원인 알려줘" 같은 관제 질문을 LangManus 구조 관제 분석 에이전트(agents/ops_analyst.py)로 보낸다.
분실인 화면에는 이 길이 없다(staff=True 는 chat_api 가 관리자 로그인을 확인한 뒤에만 넘긴다).

11/9 변재원(검토 의견 "기본 안내만 하면 supervisor 의 존재 의미가 없다"):
- 일꾼 intake(대화 접수 — agents/chat_intake.py)를 더해 챗봇으로 분실 접수·습득 신고를 끝까지 한다
- supervisor 가 일꾼 결과를 보고 다음 행동을 정한다(되묻기·확인 받기·다시 계획·접수 제안·멈춤). 판단마다
  {after, saw, decide, why} 를 decisions 에 남겨 Langfuse 'supervisor' 칸 출력과 응답(decisions)에서 볼 수 있다
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
from agents.chat_intake import FOUND_SAY, LOST_SAY, SLOT_KO as SLOT_KO_JUDGE, IntakeAgent, detect_start
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
    # 11/9 대화 접수·판단하는 감독
    session_id: str      # 화면 대화 번호(접수 대화 상태를 찾는 열쇠, 개인정보 아님)
    intake_action: dict  # 위젯 본인 확인 양식(가린 값만)
    intake_start: str    # 이번 말로 시작하는 접수 종류(lost·found) 또는 ''
    intake_active: bool  # 이미 진행 중인 접수 대화가 있음
    last: str            # 방금 끝난 일꾼
    stop: bool           # supervisor 가 남은 일꾼을 멈추기로 함(사용자 답이 필요)
    decisions: list      # supervisor 판단 기록
    offers: list         # supervisor 가 붙인 다음 행동 버튼(예: 분실 접수하기)
    reported: bool       # reporter 가 답을 정리했음 → supervisor 가 끝을 정함
    # 11/9 planner 단계별 지시서(검토 의견 "supervisor 가 planner 계획을 이행하는 모습이 안 보임")
    steps: list          # [{no, agent, task, status(todo·running·done·skipped), by(planner·supervisor), note}]
    task: str            # supervisor 가 지금 일꾼에게 넘긴 지시(일꾼 칸 입력에 보임)
    work_question: str   # 섞인 질문에서 이 일꾼 몫만 떼어 낸 말(없으면 원래 질문)


# 계획 이름(planner·supervisor 가 쓰는 짧은 이름) → 그래프 칸(에이전트) 이름. Langfuse 나무의 칸 이름과 같게 보여 준다
# 11/9 인사만 있는 말(규칙). 물음·부탁이 섞이면 인사로 보지 않는다
GREET_RE = re.compile(r"(?:(?:안녕(?:하세요|하세용)?|반가워(?:요)?|반갑습니다|반갑네요|좋은\s*(?:아침|저녁|하루|오후)(?:입니다|이에요|에요|예요|요)?"
                      r"|하이|헬로|ㅎㅇ|(?:여기\s*)?처음\s*왔(?:어요|어|습니다|네요)(?:\s*사이트\s*사용법)?)[\s!.~,ㅎㅋ^]*)+")


STEP_AGENT = {'guidance': 'researcher', 'item_search': 'item_search', 'intake': 'intake', 'ops': 'ops_analyst'}


# 직원 관제 질문: 기록을 세고 원인을 찾는 말(STRONG)이 있거나, 문제 낱말 + 기간 낱말이 같이 있을 때만.
# "본인인증 실패하면?"·"반환 절차 알려줘" 같은 이용 안내 질문은 직원이 물어도 안내 길로 간다.
OPS_STRONG = re.compile(r'원인|현황|통계|요약|보고|분석|몇건|건수|경보|처리시간|평균시간|p95|성공률|실패율|보류된|보류중|막혀|막히|병목|사례번호|몇번있|몇회')
OPS_TOPIC = re.compile(r'실패|보류|거절|느려|오래|로봇|반환|챗봇|집기|정지|알림')
OPS_WHEN = re.compile(r'오늘|어제|최근|이번|지금까지|요즘|방금')
HOW_TO = re.compile(r'방법|절차|어떻게하|하면|사용법|이용법')


def is_ops_question(question):
    q = re.sub(r'[\s\u200b-\u200d\ufeff]', '', unicodedata.normalize('NFKC', question or '').lower())
    if OPS_STRONG.search(q):
        return True
    return bool(OPS_TOPIC.search(q) and OPS_WHEN.search(q) and not HOW_TO.search(q))


SPLIT = re.compile(r'\s*(?:그리고|그리고요|,|\?|\.|!|그 다음에|다음에|하고서?\s|찾고\s|찾아\s?주고\s|찾아보고\s|보고\s|있으면\s|있는지\s?(?:보고|랑|와)?\s?)\s*')


def sub_question(question, kind):
    """11/9 planner 지시서: 한 질문에 검색과 안내가 섞이면 일꾼마다 자기 몫만 넘긴다.
    "갈색 지갑 찾아줘 그리고 받을 때 뭐 필요해?" → 검색 '갈색 지갑 찾아줘' / 안내 '받을 때 뭐 필요해'
    나누기 어려우면 원래 질문 그대로(안전한 쪽)"""
    parts = [p.strip() for p in SPLIT.split(question or '') if p and p.strip()]
    if len(parts) < 2:
        return question
    help_re = re.compile(r'방법|절차|어떻게|운영|개인정보|기간|인증|동의|예약|준비물|수령|받을|받으려|받는|주말|몇\s?시|보관|필요|챙겨|가져가|위치|어디|대신|대리|택배|수수료|비용|신분증|순서|가는\s?법')
    item_re = re.compile(r'지갑|폰|휴대|핸드|전화|배터리|보배|핸드크림|카드')
    if kind == 'guidance':
        got = [p for p in parts if help_re.search(p) and not (item_re.search(p) and not help_re.search(p))]
    else:
        got = [p for p in parts if item_re.search(p)]
    return ' '.join(got).strip() or question


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
    def __init__(self, guidance, rag=None, search=None, ops=None, brain=None, intake=None):
        """brain: coordinator·planner 를 맡을 모델(agents/chat_agents.AgentBrain). 없으면 같은 칸을 규칙으로 처리"""
        from langgraph.graph import StateGraph, START, END
        self.guidance = guidance
        self.rag = rag or GroundedRag(guidance)
        self.search = search or SearchAgent()
        self.ops = ops          # 관제 분석 에이전트(run(question) → {"report", ...}). 없으면 직원 관제 길은 닫힘
        self.brain = brain
        self.intake = intake if intake is not None else IntakeAgent(brain=brain)   # 창구 없으면 접수 대신 키오스크·웹 안내
        graph = StateGraph(ChatState)
        graph.add_node('coordinator', self._coordinator)
        graph.add_node('planner', self._planner)
        graph.add_node('supervisor', self._supervisor)
        graph.add_node('researcher', self._researcher)
        graph.add_node('item_search', self._item_search)
        graph.add_node('ops_analyst', self._ops_worker)
        graph.add_node('intake', self._intake_worker)
        graph.add_node('reporter', self._reporter)
        graph.add_edge(START, 'coordinator')
        def route_after_coordinator(s):      # 11/8: 이름 있는 함수 → Langfuse 나무에 'RunnableCallable' 대신 이 이름으로 보임
            return 'end' if s.get('result') else 'planner'

        def route_next_worker(s):
            return s['next']
        from agents.observability import router
        # 11/9 Langfuse 나무: 길 고르기 함수(라우터)는 '판단'이 아니라 supervisor 결정을 따라가는 연결선 → 알아보기 쉬운 이름 + DEBUG 단계로 낮춤
        graph.add_conditional_edges('coordinator', router(route_after_coordinator, 'edge: planner or end'), {'end': END, 'planner': 'planner'})
        graph.add_edge('planner', 'supervisor')
        graph.add_conditional_edges('supervisor', router(route_next_worker, 'edge: go to next'),
                                    {'guidance': 'researcher', 'item_search': 'item_search', 'ops': 'ops_analyst',
                                     'intake': 'intake', 'reporter': 'reporter', 'end': END})
        # 11/9 DeerFlow 그림과 같은 모양: reporter 도 supervisor 아래 일꾼 — 정리가 끝나면 supervisor 가 끝(__end__)을 정한다
        for worker in ('researcher', 'item_search', 'ops_analyst', 'intake', 'reporter'):
            graph.add_edge(worker, 'supervisor')
        self.graph = graph.compile()

    # ---------- 11/7 DeerFlow 구조의 칸들 ----------
    def _coordinator(self, state):
        """인사·감사는 정해진 짧은 답으로 끝내고, 나머지는 planner 로. 관제 질문(관리자 확인됨)은 바로 넘김"""
        from agents.chat_agents import GREETING_REPLY, THANKS_REPLY
        from agents.observability import node_step
        with node_step('coordinator', as_type='agent', input={'question': state['question']}) as obs:
            intent, routing = 'service', 'rule'
            if state.get('intake_active') or state.get('intake_start') or state.get('intake_action'):
                # 11/9 접수 대화 중이거나 접수를 시작하는 말 → 모델에 맡기지 않고 접수 길("서면이요" 같은 짧은 답을 주제 밖으로 보지 않게)
                obs.update(output={'intent': 'intake', 'routing': 'rule',
                                   'why': '진행 중인 접수 대화' if state.get('intake_active') else '접수·신고를 시작하는 말'})
                return {'intent': 'intake', 'routing': 'rule', 'path': ['coordinator']}
            if not state.get('ops_turn') and self.brain is not None:
                got = self.brain.coordinate(state['question'], state.get('questions'))
                if got is not None:
                    intent, routing = got[0], ('model' if got[1] else 'rule')
            if intent not in ('greeting', 'thanks') and not state.get('ops_turn') and GREET_RE.fullmatch(state['question'].strip()):
                intent, routing = 'greeting', 'rule'      # 11/9 채점표: "안녕! 반가워요", "좋은 아침입니다", "처음 왔어요" — 모델이 없거나 놓쳐도 인사로
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
        help_question = re.search(r'방법|절차|사용법|이용법|어떻게|운영|개인정보|보관기간|인증|동의|예약|준비물|수령|주말|몇시|보관|필요해|챙겨|가져가|위치|어디있|대신|대리|택배|수수료|비용|신분증|가는법|가는길|받는순서|순서'
                                  r'|남겨야|남기나|남겨요|적어야|써야|연락처', q) or re.search(r'후보가뭐|후보.*(?:뜻|의미|확정|사진|안나|번호만|끝|구분|맞|2개|두개|여러개|몇개)', q)   # 11/9 접수 중 "연락처도 남겨야 해요?"
        search = re.search(r'찾아(?!가|갈|올|오|와)|찾고|검색|후보(?!.*(?:뜻|의미|확정|사진|안나|번호만|끝|구분|맞|2개|두개|여러개|몇개))|접수번호|(?:지갑|모형폰|휴대폰|핸드폰|휴대전화|스마트폰|전화기|아이폰|갤럭시|usb|립밤|보조배터리|핸드크림|폰).*(?:있나요|있어|있나|있니|있습니까|있는지|있을까|들어왔|보관중|보관하고|보관하|있으면)', q)
        from agents.guidance import off_topic
        if off_topic(q):          # 11/9 서비스 밖 질문은 물건 검색을 강제하지 않음
            return {'guidance': True, 'item_search': False}
        return {'guidance': bool(help_question), 'item_search': bool((search or search_intent(q)) and not help_question) or bool(help_question and search_intent(q))}

    def _planner(self, state):
        from agents.observability import node_step
        with node_step('planner', as_type='agent', input={'question': state['question']}) as obs:
            if state.get('ops_turn'):
                plan, routing = ['ops'], 'rule'
            elif state.get('intent') == 'intake':
                plan, routing = ['intake'], 'rule'           # 접수 일꾼 먼저 — 안내가 더 필요한지는 supervisor 가 결과를 보고 정함
            elif state.get('intent') == 'off_topic':
                plan, routing = ['guidance'], 'model'        # 주제 밖: 안내 길(메뉴 버튼 답)로만 — 물건 검색 안내를 붙이지 않음
            else:
                rule = {'guidance': ['guidance'], 'search': ['item_search'], 'both': ['item_search', 'guidance']}[self._route(state)['route']]
                plan, routing = rule, 'rule'
                if self.brain is not None:
                    sig = self._signals(state)
                    must = [w for w in ('item_search', 'guidance') if sig[w]]
                    got = self.brain.plan(state['question'], state.get('questions'), must)
                    from agents.guidance import off_topic
                    if got and 'item_search' in got and off_topic(state['question']):
                        # 11/9 Mi:dm 채점(461~464): "지갑 사고 싶은데", "보조배터리 추천해줘", "휴대폰 요금제" 에 모델이 검색을 더함 → 서비스 밖이면 뺌
                        got = [w for w in got if w != 'item_search'] or ['guidance']
                    if got and 'item_search' in got and not sig['item_search']:
                        # 11/9 채점표(Mi:dm): "어떤 물건을 찾을 수 있어요?"·"후보가 뭐예요?"에 모델이 물건 검색을 더해
                        # "찾는 물건 한 종류와 색상을 알려주세요"가 붙음 → 규칙이 물건 종류를 읽지 못했으면 모델이 더한 검색은 뺌
                        from agents.lost_input import text_features
                        f, _ = text_features(state['question'])
                        if f.get('category') in (None, '확인 불가', '없음'):
                            got = [w for w in got if w != 'item_search'] or ['guidance']
                    if got:
                        plan, routing = got, 'model'
            steps = [self._step(i + 1, w, {**state, '_plan_now': plan}, 'planner') for i, w in enumerate(plan)]
            obs.update(output={'plan': plan, 'routing': routing, 'steps': [f"{x['no']}. {x['agent']} — {x['task']}" for x in steps]})
            return {'plan': plan, 'steps': steps, 'results': {}, 'path': state.get('path', []) + ['planner'], 'decisions': [], 'offers': [],
                    'last': '', 'stop': False, 'task': '',
                    'routing': 'model' if routing == 'model' or state.get('routing') == 'model' else 'rule'}

    MAX_STEPS = 6       # 일꾼 호출 상한(다시 계획이 되풀이되지 않게)

    def _step(self, no, name, state, by, note=''):
        """계획 한 단계 = {번호, 맡을 에이전트, 지시(task), 상태, 누가 정했나}. 지시는 질문에서 규칙이 읽은 값으로 구체적으로 적는다"""
        q = state.get('question') or ''
        both = {'guidance', 'item_search'} <= set(state.get('plan') or []) or (by == 'planner' and {'guidance', 'item_search'} <= set(state.get('_plan_now') or []))
        part = sub_question(q, name) if both and name in ('guidance', 'item_search') else q
        if name == 'item_search':
            from agents.lost_input import text_features
            f, _ = text_features(part)
            cat = f.get('category') if f.get('category') not in (None, '확인 불가', '없음') else '모름'
            task = f"분실물 후보 검색(읽기 전용) — 품목 {cat} · 색 {f.get('color') or '모름'}"
        elif name == 'guidance':
            try:                                               # 규칙 문서 고르기로 어느 문서를 볼지 미리 적음(모델 호출 없음)
                titles = [x['title'].split(' — ')[0] for x in (self.guidance.ask(part).get('sources') or [])][:2]
            except Exception:
                titles = []
            task = f"이용 안내 답(문서 근거만) — {' · '.join(titles) or '질문에 맞는 안내 문서 찾기'}"
        elif name == 'intake':
            kind = state.get('intake_start') or ('진행 중' if state.get('intake_active') else '')
            task = {'lost': '대화로 분실 접수 시작 — 빈칸 하나씩 묻기', 'found': '대화로 습득 신고 시작 — 빈칸 하나씩 묻기',
                    'status': '대기 번호 상태 조회'}.get(kind, '진행 중인 접수 이어 가기 — 이번 말로 빈칸 채우고 다음 칸 묻기·확인 받기')
        else:
            task = '관제 기록 분석 보고(읽기 전용, 숫자는 기록에서만)'
        return {'no': no, 'agent': STEP_AGENT.get(name, name), 'plan_name': name, 'task': task, 'status': 'todo', 'by': by,
                **({'input': part} if part != q else {}),
                **({'note': note} if note else {})}

    def _supervisor(self, state):
        """11/9 판단하는 감독: 방금 끝난 일꾼 결과를 보고 (1) 남은 일꾼을 멈출지 (2) 일꾼을 더할지 (3) 다음 행동 버튼을 붙일지 정한다.
        판단은 규칙(코드)이 하고 근거를 decisions 에 남긴다 — 모델은 일꾼 안에서 답·빈칸 채우기만 한다(로봇·접수 안전 원칙과 같음)"""
        from agents.observability import node_step
        done = state.get('results') or {}
        plan = list(state.get('plan') or [])
        decisions = list(state.get('decisions') or [])
        offers = list(state.get('offers') or [])
        stop = bool(state.get('stop'))
        last = state.get('last') or ''
        with node_step('supervisor', as_type='agent', input={'plan': plan, 'done': list(done), 'last': last}) as obs:
            if state.get('reported'):
                obs.update(output={'next': 'end', 'why': 'reporter 가 답을 정리함 → 끝'})
                return {'next': 'end', 'path': state.get('path', []) + ['supervisor']}
            if last and last in ('intake', 'item_search', 'researcher'):
                key = 'guidance' if last == 'researcher' else last
                d = self._judge(last, done.get(key) or {}, state, plan, done)
                if d:
                    decisions.append(d['record'])
                    plan = d.get('plan', plan)
                    stop = stop or d.get('stop', False)
                    offers += [o for o in d.get('offers', []) if o not in offers]
            steps = [dict(x) for x in (state.get('steps') or [])]
            for x in steps:                                   # 방금 끝난 일꾼의 단계 → 완료(결과 상태를 함께 적음)
                if x['status'] == 'running' and x['plan_name'] in done:
                    x['status'] = 'done'
                    x['result'] = (done.get(x['plan_name']) or {}).get('status')
            for name in plan:                                  # 판단으로 더해진 일꾼(add_guidance·replan) → 단계 추가(by supervisor)
                if not any(x['plan_name'] == name for x in steps):
                    why = decisions[-1]['decide'] if decisions else ''
                    steps.append(self._step(len(steps) + 1, name, state, 'supervisor', note=why))
            if stop:
                for x in steps:
                    if x['status'] == 'todo':
                        x['status'], x['note'] = 'skipped', (decisions[-1]['decide'] if decisions else 'stop')
                nxt = 'reporter'
            elif len(done) >= self.MAX_STEPS:
                nxt = 'reporter'
                decisions.append({'after': last, 'saw': f'일꾼 {len(done)}번', 'decide': 'finish', 'why': '호출 상한 — 여기서 정리'})
            else:
                nxt = next((w for w in plan if w not in done), 'reporter')
                # 11/9 use_llm(기본 끔, Langfuse chat-supervisor config): 계획에 남은 안내·검색 칸과 정리(reporter) 안에서만 모델이 고름.
                # 접수(intake)·관제(ops)·멈춤(stop)·상한은 규칙만 — 목록 밖·실패면 규칙 값 그대로
                if self.brain is not None and nxt in ('guidance', 'item_search', 'reporter'):
                    allowed = [w for w in plan if w not in done and w in ('guidance', 'item_search')] + (['reporter'] if done else [])
                    got = self.brain.choose('supervisor', allowed, nxt, {'question': state.get('question'), 'done': list(done), 'last': last})
                    if got and got != nxt:
                        decisions.append({'after': last, 'saw': f'규칙 다음 칸 {nxt}', 'decide': f'model_next:{got}',
                                          'why': '모델이 허용 목록 안에서 다른 칸을 고름(chat-supervisor use_llm)'})
                        nxt = got
            task, run, work_q = '', None, ''
            cur = next((x for x in steps if x['plan_name'] == nxt and x['status'] == 'todo'), None)
            if cur:                                           # planner 지시서의 다음 단계를 일꾼에게 넘김
                cur['status'], task, work_q = 'running', cur['task'], cur.get('input', '')
                run = {'step': f"{cur['no']}/{len(steps)}", 'agent': cur['agent'], 'task': task, **({'input': work_q} if work_q else {}),
                       'why': ('planner 계획 순서' if cur['by'] == 'planner' else f"supervisor 가 더한 단계({cur.get('note', '')})")}
            elif nxt == 'reporter':
                n_done = sum(1 for x in steps if x['status'] == 'done')
                run = {'step': 'report', 'agent': 'reporter', 'task': '일꾼 결과를 답 하나로 정리',
                       'why': (f'계획 {n_done}/{len(steps)}단계 끝' if not stop else '사용자 답이 필요해 남은 단계를 멈추고 정리')}
            obs.update(output={'next': nxt, 'run_step': run, 'plan_status': [self._step_line(x) for x in steps],
                               'decision': decisions[-1] if decisions else None})
        return {'next': nxt, 'plan': plan, 'steps': steps, 'task': task, 'work_question': work_q, 'decisions': decisions, 'offers': offers, 'stop': stop,
                'path': state.get('path', []) + ['supervisor']}

    @staticmethod
    def _step_line(x):
        mark = {'todo': '대기', 'running': '실행 중', 'done': '완료', 'skipped': '건너뜀'}[x['status']]
        tail = f" → {x['result']}" if x.get('result') else ''
        return f"{x['no']}. [{mark}] {x['agent']}: {x['task']}{tail}"


    def _judge(self, last, res, state, plan, done):
        """일꾼 결과 하나에 대한 판단. 돌려주는 값: {'record', 'plan'?, 'stop'?, 'offers'?} 또는 None(그대로 진행)"""
        q = re.sub(r'\s+', '', state.get('question') or '')
        status = res.get('status')
        rec = lambda saw, decide, why: {'after': last, 'saw': saw, 'decide': decide, 'why': why}  # noqa: E731
        if last == 'intake':
            info = res.get('intake') or {}
            if status in ('intake_question', 'intake_confirm'):
                sig = self._signals(state)
                if not info.get('progress') and sig['guidance'] and 'guidance' not in done:
                    return {'record': rec(f"접수 {info.get('stage')} · 이번 말로 채운 칸 없음 · 안내 질문 신호",
                                          'add_guidance', '접수 중에 이용 안내를 물음 → 안내 일꾼을 먼저 부르고 접수 질문은 이어서 보냄'),
                            'plan': plan + ['guidance']}
                need = '확인 버튼' if status == 'intake_confirm' else SLOT_KO_JUDGE.get(info.get('asked'), info.get('asked'))
                return {'record': rec(f"접수 {info.get('kind')} · 채움 {info.get('filled')} · 남음 {info.get('missing')}",
                                      'ask_user', f'사용자 답이 필요({need}) → 다른 일꾼을 멈추고 질문을 보냄'), 'stop': True}
            return {'record': rec(f'접수 결과 {status}', 'finish', '접수 대화가 끝남(완료·취소·실패) → 정리'), 'stop': True}
        if last == 'item_search':
            n = len(res.get('candidates') or [])
            if status == 'search_needs_details':
                return {'record': rec('검색 조건 부족', 'ask_user', '품목·색을 되물어야 함 → 검색 답(되묻기)을 그대로 보냄')}
            if n and LOST_SAY.search(q) and not FOUND_SAY.search(q):
                return {'record': rec(f'후보 {n}개', 'offer_intake', '잃어버렸다는 말 + 후보가 보임 → 대화로 분실 접수를 이어 갈 수 있게 버튼 제안'),
                        'offers': ['분실 접수하기']}
            if not n and status == 'items_not_found' and LOST_SAY.search(q) and not FOUND_SAY.search(q):
                # 11/9 채점표·정연우 검토: 후보가 없으면 끝내지 말고 분실 신고(대기 번호)로 이어 가게
                return {'record': rec('후보 0개', 'offer_intake', '잃어버렸다는 말 + 닮은 습득물 없음 → 분실 접수(대기 번호)로 이어 갈 수 있게 버튼 제안'),
                        'offers': ['분실 접수하기']}
            return {'record': rec(f'후보 {n}개 · {status}', 'continue', '다음 일꾼 또는 정리')}
        if last == 'researcher':
            no_answer = status in ('not_found', 'clarification_needed') or not res.get('sources')
            from agents.guidance import off_topic
            if res.get('generation_status') == 'off_topic' or off_topic(q.lower()):
                return {'record': rec('서비스 밖 질문', 'continue', '정해진 안내(메뉴 버튼)로 끝 — 물건 검색을 붙이지 않음')}
            if no_answer and 'item_search' not in plan and 'item_search' not in done and search_intent(q.lower()):
                return {'record': rec(f'안내 문서 답 없음({status})', 'replan_item_search', '문서에 답이 없고 물건 이름이 있음 → 물건 검색 일꾼을 더함'),
                        'plan': plan + ['item_search']}
            if any(x.get('topic') == 'chat_intake' for x in res.get('sources') or []) and not state.get('intake_active'):
                return {'record': rec('챗봇 접수 안내', 'offer_intake', '챗봇으로 접수할 수 있는지 물음 → 바로 시작할 수 있게 두 버튼 제안'),
                        'offers': ['분실 접수하기', '습득 신고하기']}
            if FOUND_SAY.search(q) and not state.get('intake_active') and re.search(r'신고|맡기|맡길|어떻게|어디', q):
                return {'record': rec('습득자 안내 질문', 'offer_intake', '주운 물건 이야기 → 챗봇으로 바로 습득 신고할 수 있게 버튼 제안'),
                        'offers': ['습득 신고하기']}
            if LOST_SAY.search(q) and re.search(r'신고|접수|어떻게', q) and not state.get('intake_active') and 'item_search' not in done:
                return {'record': rec('분실 절차 질문', 'offer_intake', '분실 신고 방법을 물음 → 챗봇으로 바로 접수할 수 있게 버튼 제안'),
                        'offers': ['분실 접수하기']}
            return {'record': rec(f'안내 답 {status}', 'continue', '다음 일꾼 또는 정리')}
        return None

    def _researcher(self, state):
        from agents.observability import node_step
        with node_step('researcher', as_type='retriever', input={'question': state.get('work_question') or state['question'],
                                                                 'task': state.get('task') or None}) as obs:
            res = self._rag_ask(state)
            obs.update(output={'status': res.get('status'), 'generation_status': res.get('generation_status'),
                               'topics': [x.get('topic') for x in res.get('sources', [])], 'answer': res.get('answer', '')[:500]})
        return {'results': {**(state.get('results') or {}), 'guidance': res}, 'path': state.get('path', []) + ['researcher'], 'last': 'researcher'}

    def _item_search(self, state):
        from agents.observability import node_step
        with node_step('item_search', as_type='tool', input={'question': state.get('work_question') or state['question'],
                                                             'task': state.get('task') or None}) as obs:
            notify('search')
            ctx, filled = state.get('search_context'), None
            # 11/9 item_search 칸 모델(chat-item-search, use_llm 기본 끔): 규칙이 품목·색을 못 읽었을 때만 목록 안에서 채움.
            # 검색 자체는 코드가 DB 를 읽기만(도구) — 모델은 검색 조건만 정한다. 색은 말에 색 낱말이 있을 때만(지어내기 막기)
            from agents import prompts
            if self.brain is not None and prompts.settings('item_search')['use_llm']:
                from agents.chat_intake import COLOR_HINT
                from agents.lost_input import text_features
                f, _ = text_features(state['question'])
                need_cat = f.get('category') in (None, '확인 불가', '없음')
                if need_cat or not f.get('color'):
                    got = self.brain.search_slots(state['question']) or {}
                    filled = {k: v for k, v in got.items()
                              if (k == 'category' and need_cat) or (k == 'color' and not f.get('color') and COLOR_HINT.search(state['question']))}
                    if filled:
                        ctx = {**(ctx or {}), **filled}
            sq = state.get('work_question') or state['question']
            from agents.chat_conversation import split_targets
            targets = [] if filled else split_targets(sq)
            if targets:                                        # 11/9 물건 여러 개("파란 폰이랑 흰 보조배터리") → 하나씩 찾아 합침
                res = self._multi_search(targets, ctx)
            else:
                res = self.search.ask(sq, _search_access.get(), ctx)
            obs.update(output={'status': res.get('status'), 'candidates': len(res.get('candidates') or []),
                               **({'targets': [f"{c}·{col or '모든 색'}" for c, col in targets]} if targets else {}),
                               **({'llm_filled': filled} if filled else {})})
        return {'results': {**(state.get('results') or {}), 'item_search': res}, 'path': state.get('path', []) + ['item_search'], 'last': 'item_search'}

    def _multi_search(self, targets, ctx):
        """물건 여러 개를 하나씩 검색(읽기 전용)해 답 하나로. 후보 번호는 1부터 이어 붙임(화면 표시용)"""
        base = {k: v for k, v in (ctx or {}).items() if k not in ('category', 'color')}
        parts, cands, first = [], [], None
        for cat, col in targets[:3]:
            name = '휴대폰' if cat == '모형폰' else cat
            r = self.search.ask(f"{col or ''} {cat} 찾아줘".strip(), _search_access.get(), base or None)
            first = first or r
            found = r.get('candidates') or []
            for c in found:
                cands.append({**c, 'candidate_no': len(cands) + 1})
            parts.append(f"· {col or '모든 색'} {name}: " + (f"후보 {len(found)}개" if found else "조건에 맞는 후보 없음"))
        n = len(cands)
        head = f"말씀하신 물건 {len(parts)}가지를 하나씩 찾았어요."
        tail = ("본인 물건으로 확정된 건 아니에요. 내 물건 같다면 '잃어버린 물건 찾기' 화면에서 분실 신고를 해 주세요."
                if n else "분실물이 없다고 확정한 것은 아닙니다. 색이나 물건 종류를 바꿔 보세요.")
        return {**(first or {}), 'candidates': cands, 'status': 'items_found' if n else 'items_not_found',
                'answer': '\n'.join([head, *parts, '', tail, '(가상 시연 관제탑 목록 — 실제 습득물이 아닙니다)']),
                'multi_search': [f"{c}·{col or '모든 색'}" for c, col in targets[:3]], 'item_search_performed': True}

    def _intake_worker(self, state):
        """11/9 대화 접수 일꾼: 빈칸 하나 묻기 → 확인 → 접수 창구 호출(agents/chat_intake.py)"""
        from agents.observability import node_step
        notify('intake')
        sid = state.get('session_id')
        with node_step('intake', as_type='agent', input={'question': state['question'], 'task': state.get('task') or None,
                                                        'start': state.get('intake_start') or None,
                                                        'form': bool(state.get('intake_action'))}) as obs:
            res = self.intake.step(sid, state['question'], start=state.get('intake_start') or None, action=state.get('intake_action'),
                                   prior=state.get('questions'))
            obs.update(output={'status': res.get('status'), **(res.get('intake') or {})})
        return {'results': {**(state.get('results') or {}), 'intake': res}, 'path': state.get('path', []) + ['intake'], 'last': 'intake'}

    def _ops_worker(self, state):
        notify('analyze')
        from agents.observability import node_step
        with node_step('ops_analyst', as_type='agent', input={'question': state['question'], 'task': state.get('task') or None}) as obs:
            res = self._ops(state)['result']
            obs.update(output={'focus': res.get('ops_focus')})
        return {'results': {**(state.get('results') or {}), 'ops': res}, 'path': state.get('path', []) + ['ops_analyst'], 'last': 'ops_analyst'}

    def _reporter(self, state):
        """일꾼 결과를 화면에 낼 답 하나로(두 개면 기존 combined 방식: 안내 → 검색 순)"""
        out = self._report(state)
        res = out['result']
        offers = [o for o in (state.get('offers') or []) if o not in (res.get('choices') or [])]
        if offers:
            res = {**res, 'choices': (list(res.get('choices') or []) + offers)[:4]}
        out['result'] = {**res, 'decisions': state.get('decisions') or [],
                         'plan_steps': [self._step_line(x) for x in (state.get('steps') or [])]}
        out['reported'] = True
        out['last'] = 'reporter'
        return out

    def _report(self, state):
        r = state.get('results') or {}
        if 'ops' in r:
            return {'result': r['ops'], 'route': 'ops', 'path': state.get('path', []) + ['reporter']}
        if 'intake' in r and r['intake'].get('status') != 'intake_none':
            res = r['intake']
            if 'guidance' in r:            # 접수 중에 안내를 물음 → 안내 답 + 이어서 접수 질문
                res = {**res, 'answer': r['guidance']['answer'] + '\n\n' + res['answer'], 'sources': r['guidance'].get('sources', []),
                       'generation_used': r['guidance'].get('generation_used', False)}
            return {'result': res, 'route': 'intake', 'path': state.get('path', []) + ['reporter']}
        if 'guidance' in r and 'item_search' in r and r['guidance'].get('status') == 'item_search_not_supported':
            # 11/9 실제 모델 시험("갈색이에요" 이어 묻기): 검색을 해 놓고 앞에 "이 챗봇은 검색하지 않습니다"가 붙어 모순 → 검색 결과만
            return {'result': r['item_search'], 'route': 'search', 'path': state.get('path', []) + ['reporter']}
        if 'guidance' in r and 'item_search' in r:
            guide, search = r['guidance'], r['item_search']
            # 11/9 reporter 칸 모델(chat-reporter, use_llm 기본 끔): 두 결과를 어떤 순서로 보일지만 허용 목록 안에서 고름.
            # 내용은 일꾼 결과 그대로(더하거나 빼지 않음) — 실패·목록 밖이면 규칙 순서(안내 → 검색)
            order = 'guidance_first'
            if self.brain is not None:
                got = self.brain.choose('reporter', ['guidance_first', 'search_first'], order,
                                        {'question': state.get('question'), 'guidance_status': guide.get('status'),
                                         'candidates': len(search.get('candidates') or [])})
                order = got or order
            first, second = (guide, search) if order == 'guidance_first' else (search, guide)
            result = {**search, 'answer': first['answer'] + '\n\n' + second['answer'], 'report_order': order,
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
        help_question = re.search(r'방법|절차|사용법|이용법|어떻게|운영|개인정보|보관기간|인증|동의|예약|준비물|수령|주말|몇시|보관|필요해|챙겨|가져가|위치|어디있|대신|대리|택배|수수료|비용|신분증|가는법|가는길|받는순서|순서', q) or re.search(r'후보가뭐|후보.*(?:뜻|의미|확정|사진|안나|번호만|끝|구분|맞|2개|두개|여러개|몇개)', q)  # 11/5: 후보의 뜻을 묻는 질문은 안내로
        search = re.search(r'찾아(?!가|갈|올|오|와)|찾고|검색|후보(?!.*(?:뜻|의미|확정|사진|안나|번호만|끝|구분|맞|2개|두개|여러개|몇개))|접수번호|(?:지갑|모형폰|휴대폰|핸드폰|휴대전화|스마트폰|전화기|아이폰|갤럭시|usb|립밤|보조배터리|핸드크림|폰).*(?:있나요|있어|있나|있니|있습니까|있는지|있을까|들어왔|보관중|보관하고|보관하|있으면)', q)
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
        q = state.get('work_question') or state['question']
        return self.rag.ask(q, history=history) if history else self.rag.ask(q)

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

    def ask(self, question, access_token=None, context=None, history=None, staff=False, session_id=None, channel='web',
            intake_action=None):
        """session_id: 같은 화면 대화를 Langfuse 에서 묶는 번호(화면이 만든 무작위 값, 개인정보 아님). channel: web·kiosk·staff"""
        from agents.observability import conversation, step
        with conversation(session_id=session_id, tags=[channel]):
            with step('lost-found-chatbot', as_type='chain', input={'question': question}) as root:
                out = self._ask(question, access_token, context, history, staff, session_id, intake_action)
                root.update(output={'answer': out.get('answer', '')[:800], 'agent': out.get('agent'),
                                    'path': out.get('agent_path'), 'routing': out.get('routing'),
                                    'generation_status': out.get('generation_status'),
                                    'decisions': out.get('decisions'), 'intake': out.get('intake')})
        from agents.observability import flush_soon
        flush_soon()                 # 11/9 질문 하나가 끝나면 바로 Langfuse 로(관제탑을 끌 때까지 기다리지 않음)
        return out

    def _ask(self, question, access_token=None, context=None, history=None, staff=False, session_id=None, intake_action=None):
        question = checked_text(question, '질문', 500)
        from agents.guidance import fix_typos
        question = fix_typos(question)          # 11/9 '지깝 일어버림' 같은 흔한 오타(앞 대화 해석·검색·모델 모두 바로잡힌 글을 봄)
        context = checked_context(context)
        turns = checked_turns(history)          # 11/7 앞 질문 + 챗봇 답(모델 맥락용)
        history = checked_history(history)
        ops_turn = bool(staff and self.ops is not None and is_ops_question(question))
        intake_active = bool(not ops_turn and self.intake.wants(session_id, question))
        intake_start = '' if ops_turn or intake_active else (detect_start(question) or '')
        if ops_turn:            # 관제 질문은 앞 대화와 합치지 않고 그대로 분석한다
            resolved = False
        elif intake_active or intake_start or intake_action:
            resolved = False    # 11/9 접수 대화의 짧은 답("서면이요")을 앞 질문과 합치지 않는다(접수 일꾼이 지금 묻는 칸으로 읽음)
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
                                           'history': turns if turns else history, 'questions': history,
                                           'session_id': session_id or '', 'intake_action': intake_action,
                                           'intake_start': intake_start, 'intake_active': intake_active},
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
