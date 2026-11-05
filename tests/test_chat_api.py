"""AI 챗봇 위젯 API(agents/chat_api.py) 시험 — 가짜 fastapi 로 경로·오류 코드·위젯 파일만 확인(11/5, LF-5).
진짜 챗봇(LangGraph) 동작은 tests/test_chatbot.py 등 정연우 시험이 맡는다."""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeGuidance:
    def __init__(self):
        self.recorded = []

    def suggestions(self):
        return {"items": [{"id": "a", "text": "분실물은 어떻게 찾나요?"}]}

    def record_suggestion(self, sid, q):
        self.recorded.append((sid, q))


class FakeBot:
    def __init__(self):
        self.guidance = FakeGuidance()
        self.rag = types.SimpleNamespace(model=None)
        self.search = types.SimpleNamespace(mode="demo_sqlite")
        self.calls = []

    def ask(self, question, token=None, context=None, history=None):
        self.calls.append((question, token, context, history))
        if not isinstance(question, str) or not question.strip():
            raise ValueError("질문은 1~500자로 입력하세요")
        if question == "고장":
            raise RuntimeError("모델 연결 실패")
        return {"answer": "안내", "agent": "guidance", "status": "answered", "sources": []}


class ChatRoutesTest(unittest.TestCase):
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
        self._saved = {k: sys.modules.get(k) for k in ("fastapi", "fastapi.responses")}
        sys.modules["fastapi"], sys.modules["fastapi.responses"] = fake, responses
        self.HTTPException, self.app = HTTPException, App()

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    def code(self, fn, *a):
        with self.assertRaises(self.HTTPException) as cm:
            fn(*a)
        return cm.exception.status_code

    def test_question_suggestion_health(self):
        from agents.chat_api import add_chat_routes
        bot = FakeBot()
        add_chat_routes(self.app, bot)
        ask = self.routes[("POST", "/chat/questions")]
        out = ask({"question": "분실물은 어떻게 찾나요?", "history": ["앞 질문"], "suggestion_id": "a"}, "Bearer tok-1")
        self.assertEqual(out["answer"], "안내")
        self.assertEqual(bot.calls[-1], ("분실물은 어떻게 찾나요?", "tok-1", None, ["앞 질문"]))   # Bearer 만 토큰으로
        self.assertEqual(bot.guidance.recorded[-1], ("a", "분실물은 어떻게 찾나요?"))
        ask({"question": "다른 질문"}, "Basic xyz")
        self.assertIsNone(bot.calls[-1][1])                                   # Bearer 가 아니면 토큰 없음
        self.assertEqual(self.code(ask, {"question": "  "}, None), 422)      # 빈 질문
        self.assertEqual(self.code(ask, {"question": "고장"}, None), 503)    # 모델 실패
        self.assertEqual(self.routes[("GET", "/chat/suggestions")]()["items"][0]["id"], "a")
        h = self.routes[("GET", "/chat/health")]()
        self.assertEqual((h["ready"], h["search_mode"], h["rag_model_configured"]), (True, "demo_sqlite", False))

    def test_chatbot_not_ready_is_503_and_tower_still_builds(self):
        from agents.chat_api import LazyChatbot, add_chat_routes

        def broken():
            raise ImportError("No module named 'langgraph'")
        add_chat_routes(self.app, LazyChatbot(broken))
        self.assertEqual(self.code(self.routes[("POST", "/chat/questions")], {"question": "안녕"}, None), 503)
        self.assertEqual(self.code(self.routes[("GET", "/chat/suggestions")]), 503)
        h = self.routes[("GET", "/chat/health")]()
        self.assertFalse(h["ready"])
        self.assertIn("설치·설정", h["error"])
        self.assertNotIn("langgraph", h["error"])

    def test_lazy_chatbot_builds_once_and_retries_after_failure(self):
        from agents.chat_api import LazyChatbot
        n = {"calls": 0}

        def flaky():
            n["calls"] += 1
            if n["calls"] == 1:
                raise RuntimeError("처음엔 실패")
            return "BOT"
        lazy = LazyChatbot(flaky)
        with self.assertRaises(RuntimeError):
            lazy.get()
        self.assertEqual((lazy.get(), lazy.get(), n["calls"], lazy.error), ("BOT", "BOT", 2, None))

    def test_internal_failure_details_are_not_returned_by_health_or_question(self):
        from agents.chat_api import LazyChatbot, add_chat_routes
        secret = 'SYNTHETIC_PRIVATE_DSN_TOKEN'
        def broken():
            raise RuntimeError(secret)
        add_chat_routes(self.app, LazyChatbot(broken))
        health = self.routes[('GET', '/chat/health')]()
        self.assertFalse(health['ready'])
        self.assertNotIn(secret, str(health))
        class FailingBot(FakeBot):
            def ask(self, *_args):
                raise RuntimeError(secret)
        add_chat_routes(self.app, FailingBot())
        with self.assertRaises(self.HTTPException) as failure:
            self.routes[('POST', '/chat/questions')]({'question': '안녕'}, None)
        self.assertEqual(failure.exception.status_code, 503)
        self.assertNotIn(secret, str(failure.exception.detail))

    def test_widget_files(self):
        from agents.chat_api import add_chat_routes
        add_chat_routes(self.app, FakeBot())
        js = self.routes[("GET", "/chat-widget/widget.js")]()
        self.assertTrue(os.path.isfile(js.path))
        self.assertEqual(js.media_type, "application/javascript")
        with open(js.path, encoding="utf-8") as source:
            src = source.read()
        for needle in ("data-chatbot-open", "/chat/questions", "attachShadow", "isComposing", "LostFoundChat"):
            self.assertIn(needle, src)
        self.assertNotIn("localStorage", src)                                  # 대화는 저장하지 않음
        demo = self.routes[("GET", "/chat-widget/demo")]().body
        self.assertIn("data-chatbot-open", demo)
        self.assertIn('src="/chat-widget/widget.js"', demo)


class ChatbotFromEnvTest(unittest.TestCase):
    def test_demo_db_off_and_real_db_never_falls_back(self):
        try:
            import langgraph  # noqa: F401
        except ImportError:
            self.skipTest("langgraph 필요(관제탑 PC·CI 에서 실행)")
        from agents import chat_api
        old = {k: os.environ.get(k) for k in ("LF_CHAT_DATABASE_URL", "TOWER_CHAT_DEMO_DB", "LF_CHAT_RAG_MODEL")}
        try:
            os.environ.pop("LF_CHAT_DATABASE_URL", None)
            os.environ.pop("LF_CHAT_RAG_MODEL", None)
            os.environ["TOWER_CHAT_DEMO_DB"] = "0"
            self.assertIsNone(chat_api.build_chatbot_from_env().search.database)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_real_chatbot_answers_through_routes(self):
        """진짜 챗봇(LangGraph + 가상 물건 DB)을 위젯 주소로 끝까지 — CI·관제탑 PC 에서만"""
        try:
            import langgraph  # noqa: F401
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("langgraph·fastapi 필요(관제탑 PC·CI 에서 실행)")
        import tempfile
        from agents import chat_api
        old = {k: os.environ.get(k) for k in ("LF_CHAT_DATABASE_URL", "TOWER_CHAT_DEMO_DB", "LF_CHAT_RAG_MODEL")}
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.environ.pop("LF_CHAT_DATABASE_URL", None)
                os.environ.pop("LF_CHAT_RAG_MODEL", None)
                os.environ["TOWER_CHAT_DEMO_DB"] = os.path.join(tmp, "demo.sqlite3")
                app = FastAPI()
                chat_api.add_chat_routes(app)
                c = TestClient(app)
                self.assertEqual(c.get("/chat/health").json()["search_mode"], "demo_sqlite")
                guide = c.post("/chat/questions", json={"question": "분실물은 어떻게 찾나요?"})
                self.assertEqual(guide.status_code, 200)
                self.assertTrue(guide.json()["answer"])
                found = c.post("/chat/questions", json={"question": "검정 지갑 찾아줘"}).json()
                self.assertTrue(found["answer"])
                self.assertIn(found["agent"], ("search", "both"))
                for cand in found.get("candidates", []):                       # 공개 칸만(접수 번호·역 없음)
                    self.assertLessEqual(set(cand), {"candidate_no", "category", "color"})
                self.assertEqual(c.post("/chat/questions", json={"question": ""}).status_code, 422)
                self.assertEqual(c.get("/chat-widget/widget.js").status_code, 200)
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v


if __name__ == "__main__":
    unittest.main()
