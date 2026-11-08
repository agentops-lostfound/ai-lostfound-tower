"""11/8 챗봇 진행률 스트림(POST /chat/questions "stream": true) 시험 — LF-13 변재원

- 단계 줄 순서(질문 받음 → 안내 자료 → 답 쓰기 → 근거 검사 → 다시 쓰기 → 다시 검사)와 퍼센트가 줄지 않는지
- 마지막 줄 {"done": true, ...} 에서 done 을 뺀 값이 기존 한 번에 받는 응답과 같은지
- stream 을 요청하지 않으면 기존 응답 그대로인지, 오류도 마지막 줄로 알리는지
모델은 가짜(느린) 모델 — 실제 Ollama 없이 돈다.
"""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import langgraph  # noqa: F401
    READY = True
except ImportError:      # fastapi·langgraph 가 없는 PC 는 건너뜀
    READY = False

from agents.chat_progress import STAGES, listening, notify  # noqa: E402

WALLET_Q = "지갑은 어느 쪽이 위로 가게 놓나요?"


def say(ev, sen, **extra):
    return {"mode": "answer", "passage_ids": [0], "sentences": [{"evidence": ev, "sentence": sen}], **extra}


def slow_model(*replies, delay=0.05):
    """한 번 부를 때마다 delay 초 걸리는 가짜 모델(진행률 확인용)"""
    queue = list(replies)

    def request(payload):
        time.sleep(delay)
        if not queue:
            raise OSError("down")
        return {"message": {"content": json.dumps(queue.pop(0))}}
    return request


def retry_replies():
    # 첫 답은 지갑을 물었는데 휴대폰 이야기 → 질문-답 맞물림 검사에 걸려 한 번 다시 씀(tests/test_chat_answer_gap.py 와 같은 흐름)
    return (say("휴대폰은 케이스(뒷면)가 위로", "휴대폰은 케이스 뒷면이 위로 가게 놓아야 해요."),
            say("지갑은 펼치지 말고 앞면이 위로 오게 두면 돼요", "지갑은 펼치지 말고 앞면이 위로 오게 두면 돼요.", answerable=True))


class ProgressNotifyTest(unittest.TestCase):
    def test_without_listener_is_noop(self):
        notify("write")      # 듣는 쪽이 없으면 아무 일도 없음

    def test_listener_errors_are_swallowed(self):
        def bad(stage):
            raise RuntimeError("화면 끊김")
        with listening(bad):
            notify("write")      # 알림 실패가 챗봇을 멈추면 안 됨

    def test_stage_percents_increase(self):
        order = ["received", "route", "retrieve", "search", "analyze", "write", "check", "rewrite", "recheck"]   # 11/8 물건 찾기·관제 분석 단계 추가
        self.assertEqual(list(STAGES), order)
        self.assertEqual([STAGES[s] for s in order], sorted(STAGES[s] for s in order))
        self.assertLess(max(STAGES.values()), 100)


@unittest.skipUnless(READY, "fastapi·langgraph 필요")
class ChatStreamTest(unittest.TestCase):
    def client(self, model_request=None, model="m"):
        from agents.chat_api import add_chat_routes
        from agents.chat_rag import GroundedRag
        from agents.chat_search import SearchAgent
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        guide = Guidance()
        bot = Chatbot(guide, rag=GroundedRag(guide, model=model, request=model_request), search=SearchAgent(None))
        app = FastAPI()
        add_chat_routes(app, chatbot=bot)
        return TestClient(app)

    @staticmethod
    def lines(resp):
        return [json.loads(x) for x in resp.text.splitlines() if x.strip()]

    def test_stage_order_and_final_line_matches_plain_response(self):
        plain = self.client(slow_model(*retry_replies())).post("/chat/questions", json={"question": WALLET_Q})
        self.assertEqual(plain.status_code, 200)
        self.assertTrue(plain.headers["content-type"].startswith("application/json"))
        streamed = self.client(slow_model(*retry_replies())).post("/chat/questions", json={"question": WALLET_Q, "stream": True})
        self.assertEqual(streamed.status_code, 200)
        self.assertTrue(streamed.headers["content-type"].startswith("application/x-ndjson"))
        rows = self.lines(streamed)
        stages = [r["stage"] for r in rows if "stage" in r]
        self.assertEqual(stages, ["received", "retrieve", "write", "check", "rewrite", "recheck"])
        pcts = [r["pct"] for r in rows if "pct" in r]
        self.assertEqual(pcts, sorted(pcts))                 # 줄어들지 않음
        self.assertTrue(all(0 < p < 100 for p in pcts))
        last = rows[-1]
        self.assertIs(last.pop("done"), True)
        self.assertEqual(last, plain.json())                # 마지막 줄 = 기존 응답 그대로
        self.assertEqual(sum(1 for r in rows if r.get("done")), 0)   # done 은 마지막 한 줄만(위에서 pop)

    def test_accept_header_also_streams(self):
        resp = self.client(slow_model(*retry_replies())).post("/chat/questions", json={"question": WALLET_Q},
                                                               headers={"Accept": "application/x-ndjson"})
        rows = self.lines(resp)
        self.assertEqual(rows[0], {"stage": "received", "pct": STAGES["received"]})
        self.assertTrue(rows[-1]["done"])

    def test_rule_answer_without_model_is_short(self):
        c = self.client(model=None)
        plain = c.post("/chat/questions", json={"question": "분실물 확인은 어디서 할 수 있나요?"}).json()
        rows = self.lines(c.post("/chat/questions", json={"question": "분실물 확인은 어디서 할 수 있나요?", "stream": True}))
        self.assertNotIn("write", [r.get("stage") for r in rows])      # 모델이 없으면 답 쓰기 단계 없음
        last = rows[-1]
        last.pop("done")
        self.assertEqual(last, plain)

    def test_errors_arrive_as_last_line(self):
        rows = self.lines(self.client(model=None).post("/chat/questions", json={"question": "", "stream": True}))
        self.assertEqual(rows[0]["stage"], "received")
        self.assertEqual(rows[-1]["done"], True)
        self.assertEqual(rows[-1]["error"], True)
        self.assertEqual(rows[-1]["status_code"], 422)
        self.assertNotIn("answer", rows[-1])

    def test_without_stream_flag_response_is_unchanged(self):
        resp = self.client(model=None).post("/chat/questions", json={"question": "분실물 확인은 어디서 할 수 있나요?", "stream": "yes"})
        self.assertTrue(resp.headers["content-type"].startswith("application/json"))     # true(불리언)만 스트림
        self.assertIn("answer", resp.json())

    def test_metrics_count_streamed_questions(self):
        c = self.client(model=None)
        c.post("/chat/questions", json={"question": "분실물 확인은 어디서 할 수 있나요?", "stream": True})
        c.post("/chat/questions", json={"question": "", "stream": True})
        q = c.get("/chat/metrics").json()["requests"]["question"]
        self.assertEqual((q["ok"], q["rejected"]), (1, 1))
        self.assertIsNotNone(q["p50_ms"])        # 위젯이 예상 시간으로 쓰는 값


if __name__ == "__main__":
    unittest.main()
