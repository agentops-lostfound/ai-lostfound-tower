"""11/9 실제 모델(Mi:dm) 시험에서 찾은 챗봇 허점 — 다시 망가지지 않게 모델 없이 확인한다.
① 답할 수 있는 질문을 모델이 되물음(버튼 글자 깨짐) ② "본센터 어디 있어요?" 규칙 빈칸
③ 오타("지깝 일어버림")를 서비스 밖으로 봄 ④ 이어 묻기에서 "검색하지 않습니다" + 검색 결과가 함께 나옴 ⑤ 검색 답이 너무 김"""
import json
import tempfile
import unittest
from pathlib import Path

from agents.chat_rag import GroundedRag
from agents.chat_search import SearchAgent, DemoItemDatabase
from agents.chatbot import Chatbot
from agents.guidance import Guidance, fix_typos


def fake(out):
    return lambda payload: {"message": {"content": json.dumps(out, ensure_ascii=False)}}


class ChatFixes1109(unittest.TestCase):
    def setUp(self):
        self.guide = Guidance()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bot = Chatbot(self.guide, search=SearchAgent(DemoItemDatabase(Path(tmp.name) / 'demo.sqlite3')))

    def topics(self, q):
        r = self.guide.ask(q)
        return [s["topic"] for s in r["sources"]], r["answer"]

    def test_center_location_question_gets_fixed_answer(self):
        for q in ["본센터 어디 있어요?", "센터 위치 알려줘", "본센터 가는 길 알려주세요"]:
            with self.subTest(q=q):
                topics, answer = self.topics(q)
                self.assertIn("center_contact", topics)
                self.assertIn("부산역", answer)

    def test_what_to_bring_is_pickup(self):
        for q in ["찾으러 가려면 뭐 가져가요?", "받으러 갈 때 뭘 챙겨야 돼요?", "뭐 들고 가야 해요?"]:
            with self.subTest(q=q):
                topics, answer = self.topics(q)
                self.assertIn("pickup", topics)
                self.assertIn("신분증", answer)

    def test_common_typos_are_fixed(self):
        self.assertEqual(fix_typos("지깝 일어버림 ㅠ"), "지갑 잃어버림 ㅠ")
        self.assertEqual(fix_typos("핸펀 이러버렸어요"), "휴대폰 잃어버렸어요")
        self.assertEqual(fix_typos("보조 베터리 찾아요"), "보조배터리 찾아요")
        for same in ["이어폰 잃어버렸어요", "일어나서 지갑 봤어요", "잊어버렸어요", "지갑 잃어버렸어요"]:
            self.assertEqual(fix_typos(same), same)
        r = self.bot.ask("지깝 일어버림 ㅠ")
        self.assertNotEqual(r.get("generation_status"), "off_topic")
        self.assertIn("지갑", r["answer"])

    def test_follow_up_search_has_no_contradiction(self):
        # 실제 모델 시험에서는 planner 가 안내·검색을 둘 다 불렀고, 안내 쪽이 "검색하지 않습니다"를 냄 → reporter 가 검색 결과만 낸다
        search = self.bot.search.ask("갈색 지갑 찾아줘")
        guide = self.guide.ask("갈색 지갑 찾아줘")
        self.assertEqual(guide["status"], "item_search_not_supported")
        out = self.bot._reporter({"results": {"guidance": guide, "item_search": search}, "path": []})["result"]
        self.assertNotIn("검색하지 않습니다", out["answer"])
        self.assertEqual(out["answer"], search["answer"])

    def test_model_clarify_is_not_shown(self):
        rag = GroundedRag(self.guide, "m", request=fake(
            {"mode": "clarify", "passage_ids": [0], "follow_up": "부산역에 있는 본센터가 어디인지 말씀해 주시겠어요?",
             "choices": ["네, 신분증을 가져가야 찾을 수 있요", "아니요"]}))
        r = rag.ask("주운 사람한테 사례하고 싶어요")          # 규칙에 안 걸리고 문서 검색만 걸리는 질문
        self.assertNotIn("말씀해 주시겠어요", r["answer"])
        self.assertFalse(any("있요" in c for c in r.get("choices") or []))

    def test_every_topic_button_is_korean(self):
        from agents.chat_rag import topic_question
        for d in self.guide.documents:
            with self.subTest(topic=d["topic"]):
                self.assertNotIn(d["topic"], topic_question(d["topic"]))

    def test_search_answer_is_short(self):
        r = self.bot.ask("검정 립밤 찾아줘")                     # 11/11 운영 품목 카드지갑 → 립밤(시연 DB DEMO-001)
        self.assertTrue(r["answer"].startswith("후보"))          # 핵심이 먼저
        self.assertLessEqual(r["answer"].count("\n"), 3)
        self.assertIn("실제 습득물이 아닙니다", r["answer"])        # 고지는 한 줄로 남음


if __name__ == "__main__":
    unittest.main()


class LiveCheckToolTest(unittest.TestCase):
    """tools/chat_live_check.py 판정이 맞는지(모델 없이)"""
    def test_check_rules(self):
        from tools.chat_live_check import check, QUESTIONS
        item = {"q": "x", "any": ["부산역"], "not": ["말씀해 주시겠어요"], "status_not": ["generated_clarification"]}
        self.assertEqual(check(item, {"answer": "본센터는 부산역에 있어요."}), [])
        self.assertTrue(check(item, {"answer": "본센터가 어디인지 말씀해 주시겠어요?", "generation_status": "generated_clarification"}))
        self.assertTrue(check({"q": "x"}, {"answer": "네", "choices": ["찾을 수 있요"]}))          # 깨진 낱말 끝
        self.assertTrue(check({"q": "x"}, {"answer": "네", "choices": ["finder_privacy 알려줘"]}))   # 영어 주제 이름
        self.assertEqual(check({"q": "x"}, {"answer": "있어요. 없어요."}), [])
        items = json.loads(QUESTIONS.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(items), 15)
        self.assertTrue(all(set(i) <= {"q", "history", "any", "not", "status_not"} for i in items))


class PlannerFoundSideTest(unittest.TestCase):
    def test_model_cannot_add_search_to_found_side_question(self):
        from agents.chat_agents import AgentBrain
        brain = AgentBrain.__new__(AgentBrain)
        brain._ask = lambda *a, **k: {"steps": ["item_search", "guidance"]}
        self.assertEqual(brain.plan("휴대폰은 상자에 어떻게 넣어요?", [], ["guidance"]), ["guidance"])
        self.assertEqual(brain.plan("지갑 주웠는데 어디 맡겨요?", [], ["guidance"]), ["guidance"])
        self.assertIn("item_search", brain.plan("지갑 놓고 내렸어요 어떻게 해요", [], ["guidance"]))   # 잃어버린 쪽은 그대로
        self.assertIn("item_search", brain.plan("휴대폰 넣어 둔 가방 잃어버림", [], ["item_search", "guidance"]))  # 규칙이 정한 검색은 못 뺌


class LiveCheckModelReadyTest(unittest.TestCase):
    def test_missing_model_is_reported(self):
        from tools.chat_live_check import model_ready
        self.assertIn("Ollama 에 연결할 수 없어요", model_ready("midm-2.0-mini", None))
        self.assertIn("없어요", model_ready("midm-2.0-mini", ["exaone3.5:2.4b", "mistral:latest"]))
        self.assertEqual(model_ready("midm-2.0-mini", ["midm-2.0-mini:latest"]), "")
        self.assertEqual(model_ready("exaone3.5:2.4b", ["exaone3.5:2.4b"]), "")


class LiveCheckModelProbeTest(unittest.TestCase):
    """11/9 교육원: 모델 목록엔 있는데 대화가 실패해 문항마다 0.1초 — 진짜 오류 문장을 먼저 보여 주는지"""

    def test_ok_http_error_and_bad_reply(self):
        import io
        import urllib.error
        from tools.chat_live_check import model_probe
        self.assertEqual(model_probe("m", lambda p: {"message": {"content": '{"ok": true}'}}), "")

        def http_400(payload):
            raise urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO('{"error":"모델 형식 오류"}'.encode()))
        why = model_probe("m", http_400)
        self.assertIn("HTTP 400", why)
        self.assertIn("모델 형식 오류", why)
        self.assertIn("JSONDecodeError", model_probe("m", lambda p: {"message": {"content": "그냥 글"}}))
        self.assertIn("ConnectionRefusedError", model_probe("m", lambda p: (_ for _ in ()).throw(ConnectionRefusedError())))
