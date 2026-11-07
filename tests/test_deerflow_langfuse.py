"""11/7 챗봇 DeerFlow 구조(coordinator → planner → supervisor ⇄ 일꾼 → reporter)와 Langfuse 연결 시험 — 모델·Langfuse 대신 대역"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_chat_color_multiturn import setUpModule, tearDownModule  # noqa: E402,F401


def brain_with(coord=None, plan=None, log=None):
    """coordinator·planner 대역 모델: 시스템 프롬프트로 어느 칸인지 구분해 정해진 JSON 을 돌려줌"""
    from agents.chat_agents import AgentBrain

    def request(payload):
        system = payload["messages"][0]["content"]
        if log is not None:
            log.append(system[:20])
        if "coordinator" in system:
            if coord is None:
                raise OSError("down")
            return {"message": {"content": json.dumps({"intent": coord})}}
        if plan is None:
            raise OSError("down")
        return {"message": {"content": json.dumps({"steps": plan})}}
    return AgentBrain("m", request=request)


def bot(brain=None):
    from agents.chat_rag import GroundedRag
    from agents.chat_search import DemoItemDatabase, SearchAgent
    from agents.chatbot import Chatbot
    from agents.guidance import Guidance
    import tempfile
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    return Chatbot(Guidance(), rag=GroundedRag(Guidance()), search=SearchAgent(DemoItemDatabase(Path(tmp) / "d.sqlite3")), brain=brain)


class DeerFlowGraphTest(unittest.TestCase):
    def test_rule_path_without_model_goes_through_agents(self):
        r = bot().ask("운영시간 알려줘")
        self.assertEqual(r["agent_path"], ["coordinator", "planner", "supervisor", "researcher", "supervisor", "reporter"])
        self.assertEqual(r["routing"], "rule")

    def test_coordinator_greeting_ends_early(self):
        r = bot(brain_with(coord="greeting", plan=["guidance"])).ask("안녕하세요")
        self.assertEqual(r["agent_path"], ["coordinator"])
        self.assertIn("분실물 안내 도우미", r["answer"])
        self.assertEqual(r["routing"], "model")

    def test_service_words_override_greeting(self):
        log = []
        r = bot(brain_with(coord="greeting", plan=["item_search"], log=log)).ask("안녕 검정 지갑 잃어버렸어요")
        self.assertNotEqual(r["agent_path"], ["coordinator"])               # 서비스 낱말 → 끊지 않음
        self.assertEqual(log.count(log[0]) if log else 0, 1)                 # coordinator 모델은 부르지 않고 planner 만

    def test_planner_model_adds_but_cannot_remove_rule_signal(self):
        r = bot(brain_with(coord="service", plan=["guidance"])).ask("파란색 휴대폰을 잃어버렸어")
        self.assertIn("item_search", r["agent_path"])                        # 규칙이 분명히 찾은 물건 검색은 남음
        both = bot(brain_with(coord="service", plan=["item_search", "guidance"])).ask("검정 지갑 찾고 본센터 가는 법도 알려줘")
        self.assertIn("researcher", both["agent_path"])
        self.assertIn("item_search", both["agent_path"])
        self.assertEqual(both["agent"], "both")

    def test_model_down_falls_back_to_rules(self):
        r = bot(brain_with(coord=None, plan=None)).ask("운영시간 알려줘")
        self.assertEqual(r["routing"], "rule")
        self.assertIn("researcher", r["agent_path"])

    def test_ops_path_never_opened_by_model(self):
        r = bot(brain_with(coord="service", plan=["guidance"])).ask("오늘 반환 실패 원인 알려줘")   # staff 아님
        self.assertNotIn("ops_analyst", r["agent_path"])


    def test_off_topic_goes_only_to_guidance(self):
        log = []
        r = bot(brain_with(coord="off_topic", plan=["item_search", "guidance"], log=log)).ask("오늘 날씨 어때?")
        self.assertNotIn("item_search", r["agent_path"])                    # 실측 11/7 허점: 날씨 질문에 물건 검색이 붙음
        self.assertEqual(len(log), 1)                                         # planner 모델은 부르지 않음

    def test_planner_item_search_dropped_without_item_words(self):
        r = bot(brain_with(plan=["item_search", "guidance"])).ask("물건 수령 절차 알려줘")
        self.assertNotIn("item_search", r["agent_path"])
        self.assertIn("researcher", r["agent_path"])
        r = bot(brain_with(plan=["item_search", "guidance"])).ask("그럼 거기 갈 때 뭐 챙겨요?", history=["물건 수령 절차 알려줘"])
        self.assertNotIn("item_search", r["agent_path"])

    def test_combined_keeps_guidance_generation_status(self):
        r = bot(brain_with(plan=["item_search", "guidance"])).ask("검정 지갑 찾고 본센터 가는 법도 알려줘")
        self.assertIn("item_search", r["agent_path"])
        self.assertIn("researcher", r["agent_path"])
        self.assertIsNotNone(r.get("generation_status"))


class LangfuseHooksTest(unittest.TestCase):
    def tearDown(self):
        from agents import observability
        observability.reset_for_tests()

    def test_disabled_without_keys_and_masking(self):
        from agents import observability
        with mock.patch.dict(os.environ, {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": "", "LANGFUSE_BASE_URL": ""}):
            observability.reset_for_tests()
            self.assertIsNone(observability.client())
            with observability.step("x", as_type="agent") as obs:
                obs.update(output={"a": 1})                                  # 아무 일 없음
        m = observability.mask(data={"q": "제 번호는 010-1234-5678, 주민 900101-1234567, a@b.com", "n": [1, "010 9999 8888"]})
        self.assertEqual(m["q"], "제 번호는 [전화번호], 주민 [주민번호], [이메일]")
        self.assertEqual(m["n"][1], "[전화번호]")

    def test_prompt_fallback_and_langfuse_prompt(self):
        from agents import observability, prompts
        with mock.patch.dict(os.environ, {"LANGFUSE_PUBLIC_KEY": ""}):
            observability.reset_for_tests()
            text, obj = prompts.get("chat-guidance-answer", clarify_rule="")
            self.assertIsNone(obj)
            self.assertNotIn("{{clarify_rule}}", text)
            self.assertIn("JSON 만 출력한다", text)

        class FakePrompt:
            is_fallback = False

            def compile(self, **kw):
                return "langfuse 버전 프롬프트 " + kw.get("clarify_rule", "")

        class FakeClient:
            def get_prompt(self, name, **kw):
                return FakePrompt()
        with mock.patch.object(observability, "client", lambda: FakeClient()):
            text, obj = prompts.get("chat-guidance-answer", clarify_rule="되묻기")
        self.assertEqual(text, "langfuse 버전 프롬프트 되묻기")
        self.assertIsNotNone(obj)

    def test_steps_are_recorded_when_client_exists(self):
        from agents import observability
        names = []

        class Obs:
            def update(self, **kw):
                pass

        class CM:
            def __init__(self, name):
                names.append(name)

            def __enter__(self):
                return Obs()

            def __exit__(self, *a):
                return False

        class FakeClient:
            def start_as_current_observation(self, name, as_type="span", **kw):
                return CM(f"{as_type}:{name}")
        with mock.patch.object(observability, "client", lambda: FakeClient()), \
                mock.patch.dict(os.environ, {"LF_LANGFUSE_CALLBACK": "0"}):          # 콜백 끔 → 칸을 직접 기록
            bot(brain_with(coord="service", plan=["guidance"])).ask("운영시간 알려줘", session_id="s-test-0001")
        for want in ("chain:lost-found-chatbot", "agent:coordinator", "agent:planner", "generation:planner-llm", "retriever:researcher"):
            self.assertIn(want, names)

        # 콜백 방식: 그래프 칸은 콜백이 기록, 직접 기록은 전체(chain)·모델 호출(generation)만 남아 겹치지 않음
        from langchain_core.callbacks import BaseCallbackHandler
        seen = []

        class Handler(BaseCallbackHandler):
            def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kw):
                seen.append(kw.get("name"))
                self.last_inputs = inputs
        names.clear()
        handler = Handler()
        with mock.patch.object(observability, "client", lambda: FakeClient()), \
                mock.patch.object(observability, "graph_callbacks", lambda: [handler]):
            bot(brain_with(coord="service", plan=["guidance"])).ask("운영시간 알려줘", access_token="secret-token-xyz")
        for node in ("coordinator", "planner", "supervisor", "researcher", "reporter"):
            self.assertIn(node, seen)
        self.assertIn("generation:planner-llm", names)
        self.assertNotIn("agent:coordinator", names)
        self.assertNotIn("secret-token-xyz", repr(handler.last_inputs))     # 접속 토큰은 기록에 들어가지 않음


class ApiSessionTest(unittest.TestCase):
    def test_session_id_passed_only_when_valid(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.chat_api import add_chat_routes
        seen = []

        class Bot:
            def __init__(self):
                from agents.guidance import Guidance
                self.guidance = Guidance()

            def ask(self, q, token, ctx, history, staff=False, session_id=None, channel="web"):
                seen.append((session_id, channel))
                return {"status": "answered", "answer": "ok", "sources": []}
        app = FastAPI()
        add_chat_routes(app, Bot())
        c = TestClient(app)
        c.post("/chat/questions", json={"question": "운영시간", "session_id": "s-abcdef12"})
        c.post("/chat/questions", json={"question": "운영시간", "session_id": "010-1234-5678 이름"})
        self.assertEqual(seen, [("s-abcdef12", "web"), (None, "web")])


if __name__ == "__main__":
    unittest.main()
