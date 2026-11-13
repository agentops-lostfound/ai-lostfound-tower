"""직원 관제 질문(챗봇 A안, 11/6 변재원 LF-5) 시험.

한줄 설명: 관리자 화면 챗봇에서만 "오늘 반환 실패 원인 알려줘" 같은 질문이 LangManus 구조 관제 분석 에이전트로 가고,
분실인 화면·로그인 안 한 요청에서는 그 길이 절대 열리지 않는지 확인한다.
- 챗봇 그래프(langgraph)·langsmith 가 없으면 이 파일이 도는 동안만 작은 대역을 끼운다(test_ops_analyst.py 와 같은 방식)
- fastapi 가 있으면(CI·관제탑 PC) 진짜 TestClient 로 Request 주입·401 까지 확인한다
"""
import contextlib
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fake_langgraph():
    START, END = "__start__", "__end__"

    class StateGraph:
        def __init__(self, _schema):
            self.nodes, self.edges, self.cond = {}, {}, {}

        def add_node(self, name, fn):
            self.nodes[name] = fn

        def add_edge(self, a, b):
            self.edges[a] = b

        def add_conditional_edges(self, a, fn, mapping):
            self.cond[a] = (fn, mapping)

        def compile(self):
            g = self

            class App:
                def invoke(self, state, config=None):
                    state, cur, n = dict(state), g.edges[START], 0
                    while cur != END:
                        n += 1
                        if n > (config or {}).get("recursion_limit", 25):
                            raise RecursionError("recursion_limit")
                        state.update(g.nodes[cur](state) or {})
                        cur = g.cond[cur][1][g.cond[cur][0](state)] if cur in g.cond else g.edges[cur]
                    return state
            return App()

    mod = types.ModuleType("langgraph.graph")
    mod.StateGraph, mod.START, mod.END = StateGraph, START, END
    return mod


_PATCHES = []


def setUpModule():
    fakes = {}
    try:
        import langgraph.graph  # noqa: F401
    except ImportError:
        fakes.update({"langgraph": types.ModuleType("langgraph"), "langgraph.graph": _fake_langgraph()})
    try:
        import langsmith  # noqa: F401
    except ImportError:
        ls = types.ModuleType("langsmith")
        ls.tracing_context = lambda **k: contextlib.nullcontext()
        fakes["langsmith"] = ls
    if fakes:
        p = mock.patch.dict(sys.modules, fakes)
        p.start()
        _PATCHES.append(p)


def tearDownModule():
    while _PATCHES:
        _PATCHES.pop().stop()


DATA = {
    "returns": [
        {"case_id": "R1", "item_id": "A-W01", "decision": "returned", "reason": "", "seconds": 12.0},
        {"case_id": "R2", "item_id": "A-W02", "decision": "rejected", "reason": "확인 질문 미통과", "seconds": 3.0},
        {"case_id": "R3", "item_id": "A-W03", "decision": "stopped", "reason": "집기 실패 2회", "seconds": 40.0},
    ],
    "live": {"events": [{"channel": "alert", "title": "[R3] 집기 실패"}], "stories": []},
}


class FakeOps:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def run(self, question):
        self.calls.append(question)
        if self.fail:
            raise RuntimeError("secret internal path /home/x")
        return {"report": "# 관제 분석 보고\n- 반환 3건 중 실패 2건", "focus": "failures", "facts": {"total": 3},
                "used_llm": [], "accepted": True}


class OpsQuestionTest(unittest.TestCase):
    def test_which_questions_are_ops(self):
        from agents.chatbot import is_ops_question
        for q in ("오늘 반환 실패 원인 알려줘", "반환 현황 요약해줘", "최근 로봇 정지 몇 건?", "챗봇 처리 시간 분석해줘",
                  "오늘 로봇 실패 있었어?", "경보 통계"):
            self.assertTrue(is_ops_question(q), q)
        for q in ("본인인증 실패하면?", "반환 절차 알려줘", "지갑 잃어버렸어요", "오늘 본센터 운영해요?",
                  "로봇이 어떻게 물건을 가져와요?", "", "검정 지갑 찾아줘"):
            self.assertFalse(is_ops_question(q), q)


class ChatbotStaffRouteTest(unittest.TestCase):
    def setUp(self):
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        from agents.chat_search import SearchAgent
        self.ops = FakeOps()
        self.bot = Chatbot(Guidance(), search=SearchAgent(None), ops=self.ops)

    def test_staff_ops_question_goes_to_ops_agent(self):
        out = self.bot.ask("오늘 반환 실패 원인 알려줘", staff=True)
        self.assertEqual(out["agent"], "ops")
        self.assertEqual(self.ops.calls, ["오늘 반환 실패 원인 알려줘"])
        self.assertIn("관제 분석 보고", out["answer"])
        self.assertEqual((out["method"], out["generation_status"], out["status"]),
                         ("langmanus_style_ops_agents", "ops_report", "answered"))
        self.assertEqual((out["sources"], out["candidates"]), ([], []))           # 위젯 응답 형식 검사 통과

    def test_public_user_never_reaches_ops(self):
        out = self.bot.ask("오늘 반환 실패 원인 알려줘")                             # staff 기본값 False
        self.assertNotEqual(out["agent"], "ops")
        self.assertEqual(self.ops.calls, [])
        self.assertNotIn("관제 분석 보고", out["answer"])

    def test_staff_how_to_question_stays_guidance(self):
        out = self.bot.ask("본인인증 실패하면?", staff=True)
        self.assertEqual(out["agent"], "guidance")
        self.assertEqual(self.ops.calls, [])

    def test_staff_ops_ignores_history_merge(self):
        out = self.bot.ask("반환 현황 요약해줘", history=["검정 지갑 찾아줘"], staff=True)
        self.assertEqual((out["agent"], out["context_used"]), ("ops", False))

    def test_ops_error_is_hidden(self):
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        from agents.chat_search import SearchAgent
        bot = Chatbot(Guidance(), search=SearchAgent(None), ops=FakeOps(fail=True))
        out = bot.ask("오늘 현황 요약", staff=True)
        self.assertEqual((out["agent"], out["status"]), ("ops", "partial"))
        self.assertNotIn("/home/x", str(out))

    def test_without_ops_agent_staff_flag_does_nothing(self):
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        from agents.chat_search import SearchAgent
        out = Chatbot(Guidance(), search=SearchAgent(None)).ask("오늘 반환 실패 원인 알려줘", staff=True)
        self.assertNotEqual(out["agent"], "ops")

    def test_real_ops_analyst_through_chatbot(self):
        """진짜 관제 분석 에이전트(모델 없음 → 계산 보고) + 관제탑 안에서 읽는 자료"""
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        from agents.chat_search import SearchAgent
        from agents.chat_api import build_ops_agent
        from agents.chat_metrics import ChatMetrics
        with mock.patch.dict(os.environ, {"OPS_ANALYST_MODEL": "", "LF_CHAT_RAG_MODEL": ""}):
            ops = build_ops_agent(lambda: DATA, ChatMetrics())
        bot = Chatbot(Guidance(), search=SearchAgent(None), ops=ops)
        out = bot.ask("오늘 반환 실패 원인 알려줘", staff=True)
        self.assertEqual((out["agent"], out["status"], out["ops_focus"], out["ops_used_llm"]),
                         ("ops", "answered", "failures", []))
        self.assertIn("확인 질문 미통과", out["answer"])
        self.assertIn("■ 핵심", out["answer"])                                      # 채팅창용: 마크다운 제목 기호 없앰
        self.assertFalse(any(line.startswith("#") for line in out["answer"].splitlines()))


class ChatApiStaffTest(unittest.TestCase):
    """가짜 fastapi 로 /chat/questions 의 mode 처리만(test_chat_api.py 와 같은 방식)"""

    def setUp(self):
        self.routes = {}
        routes = self.routes

        class HTTPException(Exception):
            def __init__(self, status_code, detail=None):
                self.status_code, self.detail = status_code, detail

        class App:
            def _reg(self, method, path):
                def deco(fn):
                    routes[(method, path)] = fn
                    return fn
                return deco

            def get(self, path, **kw):
                return self._reg("GET", path)

            def post(self, path, **kw):
                return self._reg("POST", path)

        fake = types.ModuleType("fastapi")
        fake.HTTPException, fake.Body, fake.Header = HTTPException, (lambda *a, **k: None), (lambda *a, **k: None)
        responses = types.ModuleType("fastapi.responses")
        responses.HTMLResponse = lambda content: types.SimpleNamespace(body=content)
        responses.FileResponse = lambda path, **k: types.SimpleNamespace(path=path, **k)
        p = mock.patch.dict(sys.modules, {"fastapi": fake, "fastapi.responses": responses})
        p.start()
        self.addCleanup(p.stop)
        self.HTTPException, self.app = HTTPException, App()

        class Bot:
            def __init__(self):
                self.guidance = types.SimpleNamespace(record_suggestion=lambda *a: None, suggestions=lambda: {"items": []})
                self.rag = types.SimpleNamespace(model=None)
                self.search = types.SimpleNamespace(mode="off")
                self.ops, self.calls = None, []

            def ask(self, question, token=None, context=None, history=None, staff=False):
                self.calls.append((question, staff))
                return {"answer": "ok", "agent": "ops" if staff else "guidance", "status": "answered", "sources": []}

        self.bot = Bot()

    def code(self, fn, *a, **k):
        with self.assertRaises(self.HTTPException) as cm:
            fn(*a, **k)
        return cm.exception.status_code

    def add(self, allowed=True, source=True):
        from agents.chat_api import add_chat_routes
        made = []

        def factory(src, metrics):
            made.append(src)
            return FakeOps()
        add_chat_routes(self.app, self.bot, staff_allowed=(lambda r: allowed) if allowed is not None else None,
                        ops_source=(lambda: DATA) if source else None, ops_factory=factory)
        return self.routes[("POST", "/chat/questions")], made

    def test_logged_in_staff(self):
        ask, made = self.add(allowed=True)
        out = ask({"question": "오늘 반환 실패 원인 알려줘", "mode": "staff"}, None, request=object())
        self.assertEqual(out["agent"], "ops")
        self.assertEqual(self.bot.calls[-1], ("오늘 반환 실패 원인 알려줘", True))
        ask({"question": "또", "mode": "staff"}, None, request=object())
        self.assertEqual(len(made), 1)                                             # 에이전트는 한 번만 붙임
        self.assertTrue(self.routes[("GET", "/chat/health")]()["staff_ops"])

    def test_not_logged_in_is_401_and_bot_untouched(self):
        ask, made = self.add(allowed=False)
        self.assertEqual(self.code(ask, {"question": "오늘 반환 실패 원인 알려줘", "mode": "staff"}, None, request=object()), 401)
        self.assertEqual((self.bot.calls, made), ([], []))

    def test_public_modes_never_staff(self):
        ask, _ = self.add(allowed=True)
        for body in ({"question": "q"}, {"question": "q", "mode": "web"}, {"question": "q", "mode": "kiosk"}):
            ask(body, None, request=object())
            self.assertFalse(self.bot.calls[-1][1], body)
        self.assertEqual(self.code(ask, {"question": "q", "mode": "admin"}, None, request=object()), 422)

    def test_staff_mode_without_tower_wiring_is_404(self):
        ask, _ = self.add(allowed=None, source=False)                              # lost_api 등 관제탑 밖
        self.assertEqual(self.code(ask, {"question": "q", "mode": "staff"}, None, request=object()), 404)
        self.assertFalse(self.routes[("GET", "/chat/health")]()["staff_ops"])


class RealFastApiStaffTest(unittest.TestCase):
    def test_request_injection_and_401(self):
        """진짜 FastAPI 에서 request 가 주입되는지(기본값 None 이어도) — CI·관제탑 PC 에서만"""
        try:
            import langgraph  # noqa: F401
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("langgraph·fastapi 필요(관제탑 PC·CI 에서 실행)")
        from agents.chat_api import add_chat_routes
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        from agents.chat_search import SearchAgent
        bot = Chatbot(Guidance(), search=SearchAgent(None))
        app = FastAPI()
        add_chat_routes(app, bot, staff_allowed=lambda r: r.headers.get("x-admin-key") == "k",
                        ops_source=lambda: DATA, ops_factory=lambda src, m: FakeOps())
        c = TestClient(app)
        q = {"question": "오늘 반환 실패 원인 알려줘", "mode": "staff"}
        self.assertEqual(c.post("/chat/questions", json=q).status_code, 401)
        ok = c.post("/chat/questions", json=q, headers={"X-Admin-Key": "k"})
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["agent"], "ops")
        pub = c.post("/chat/questions", json={"question": "오늘 반환 실패 원인 알려줘"}, headers={"X-Admin-Key": "k"})
        self.assertNotEqual(pub.json()["agent"], "ops")                           # mode 없으면 로그인했어도 관제 길 아님


class WidgetStaffTest(unittest.TestCase):
    def test_widget_and_admin_page(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        js = (root / "web" / "chat-widget" / "widget.js").read_text(encoding="utf-8")
        self.assertIn('if (STAFF) body.mode = "staff";', js)
        self.assertIn('res.agent === "ops"', js)
        admin = (root / "web" / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="/chat-widget/widget.js?v=20261113a" data-mode="staff" defer></script>', admin)
        for page in ("lost", "kiosk"):                                            # 분실인·키오스크는 staff 아님
            html = (root / "web" / page / "index.html").read_text(encoding="utf-8")
            self.assertNotIn('data-mode="staff"', html)


if __name__ == "__main__":
    unittest.main()
