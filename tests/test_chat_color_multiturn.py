"""11/6 챗봇 보완 시험(LF-5 변재원) — 색상 오해석 차단 + 이전 질문을 sLLM 에 맥락으로 전달.

한줄 설명: "연보라색 지갑"을 색 없이 찾아 검정 지갑을 보여 주던 허점, 두 가지 색을 막연히 되묻던 답,
이어지는 질문에서 앞 질문을 모델이 몰랐던 점을 고쳤는지 확인한다.
- langgraph·langsmith 가 없으면 이 파일이 도는 동안만 작은 대역을 끼운다(test_chat_staff_ops.py 와 같은 방식)
"""
import contextlib
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_PATCHES = []


def setUpModule():
    from test_chat_staff_ops import _fake_langgraph
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


class ColorWordsTest(unittest.TestCase):
    def test_color_words(self):
        from agents.contracts import COLORS
        from agents.lost_input import text_features
        cases = {"연보라색 지갑": "기타", "진한 보라 립밤": "기타", "주황색 USB": "기타", "하늘색 USB": "파랑",
                 "베이지 지갑": "갈색", "네이비 지갑": "남색", "연두색 핸드크림": "초록", "그레이 보조배터리": "회색",
                 "까만 지갑": "검정", "검은색 반지갑": "검정", "은색 보조배터리": "회색", "파란 지갑": "파랑"}
        for text, color in cases.items():
            self.assertEqual(text_features(text)[0].get("color"), color, text)
            self.assertIn(color, COLORS)                                   # 계약 색 목록 안에서만
        feats, warns = text_features("검정이랑 빨간 지갑")
        self.assertNotIn("color", feats)
        self.assertTrue(any(w.startswith("색상") for w in warns))
        feats, warns = text_features("검정 바탕에 보라 줄무늬 지갑")         # 목록 색 + 목록 밖 색 = 두 가지
        self.assertNotIn("color", feats)
        self.assertNotIn("color", text_features("지갑을 자주 잃어버려요")[0])   # '자주'(빈도)는 색이 아님


class SearchAnswerTest(unittest.TestCase):
    def setUp(self):
        from agents.chat_search import DemoItemDatabase, SearchAgent
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agent = SearchAgent(DemoItemDatabase(Path(self.tmp.name) / "demo.sqlite3"))

    def test_light_purple_is_not_searched_as_any_color(self):
        out = self.agent.ask("연보라색 지갑 찾아줘")
        self.assertEqual(out["search_filter"]["color"], "기타")
        self.assertNotIn("검정", [c["color"] for c in out["candidates"]])       # 예전: 색 없이 찾아 검정 지갑 후보
        self.assertIn("목록 밖 색", out["answer"])

    def test_two_colors_get_specific_question(self):
        out = self.agent.ask("검정이랑 빨간 지갑 찾아줘")
        self.assertEqual(out["status"], "search_needs_details")
        self.assertIn("가장 넓게 보이는 색 하나", out["answer"])

    def test_applied_conditions_show_values(self):
        self.assertIn("찾은 조건: 지갑 · 검정", self.agent.ask("검정 지갑 찾아줘")["answer"])
        self.assertIn("지갑 · 모든 색", self.agent.ask("지갑 찾아줘")["answer"])


class HistoryToModelTest(unittest.TestCase):
    def setUp(self):
        from agents.chat_rag import GroundedRag
        from agents.guidance import Guidance
        self.prompts = []

        def fake(payload):
            self.prompts.append(json.loads(payload["messages"][1]["content"]))
            return {"message": {"content": json.dumps({"mode": "answer", "passage_ids": [0],
                                                       "answer": "본센터에서 확인한 뒤 받을 수 있어요."})}}
        self.guide = Guidance()
        self.rag = GroundedRag(self.guide, "fake", fake)

    def test_previous_questions_reach_model_only_when_given(self):
        q = "본센터 가서 어떻게 받아요?"
        self.rag.ask(q)
        self.rag.ask(q, history=["검정 지갑 찾아줘"])
        self.assertNotIn("previous_questions", self.prompts[0])
        self.assertEqual(self.prompts[1]["previous_questions"], ["검정 지갑 찾아줘"])
        self.assertFalse(hasattr(self.rag, "_history"))                     # 객체에 저장 안 함(다른 사람과 안 섞임)

    def test_concurrent_histories_do_not_mix(self):
        from agents.chat_rag import GroundedRag
        lock = threading.Lock()
        seen = []

        def slow(payload):
            body = json.loads(payload["messages"][1]["content"])
            with lock:
                seen.append(body.get("previous_questions"))
            return {"message": {"content": json.dumps({"mode": "answer", "passage_ids": [0],
                                                       "answer": "본센터에서 확인한 뒤 받을 수 있어요."})}}
        rag = GroundedRag(self.guide, "fake", slow)
        rag._lock = threading.Lock()
        threads = [threading.Thread(target=rag.ask, args=("본센터 가서 어떻게 받아요?",), kwargs={"history": [f"질문{i}"]})
                   for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for h in seen:                                                     # 바쁘면 모델을 안 부르므로 부른 것만 확인
            self.assertEqual(len(h), 1)
            self.assertRegex(h[0], r"^질문\d$")

    def test_chatbot_passes_history_and_old_rag_still_works(self):
        from agents.chat_search import SearchAgent
        from agents.chatbot import Chatbot
        bot = Chatbot(self.guide, rag=self.rag, search=SearchAgent(None))
        bot.ask("본센터 가서 어떻게 받아요?", history=["검정 지갑 찾아줘"])
        self.assertEqual(self.prompts[-1].get("previous_questions"), ["검정 지갑 찾아줘"])

        class OldRag:                                                      # history 인자를 모르는 예전 부품
            def __init__(self, g):
                self.guidance, self.model = g, None

            def ask(self, question):
                return {"status": "answered", "answer": "안내", "sources": []}
        old = Chatbot(self.guide, rag=OldRag(self.guide), search=SearchAgent(None))
        self.assertEqual(old.ask("본센터 가서 어떻게 받아요?")["answer"], "안내")


if __name__ == "__main__":
    unittest.main()
