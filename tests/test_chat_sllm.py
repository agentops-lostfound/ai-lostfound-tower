"""11/6 sLLM + RAG 챗봇: 문서 검색·되묻기(유도 질문)·생성 답 검사 — 모델 없이 가짜 응답으로"""
import json
import unittest

from agents.chat_rag import GroundedRag, numbers_supported, topic_question
from agents.chat_retrieval import Retriever
from agents.guidance import Guidance


def fake(out):
    return lambda payload: {"message": {"content": json.dumps(out, ensure_ascii=False)}}


class RetrievalTest(unittest.TestCase):
    def test_related_passages_rank_first(self):
        r = Retriever(Guidance().documents)
        self.assertEqual(r.search("센터 문 몇시에 닫아요")[0]["topic"], "hours")
        self.assertEqual(r.search("가방 주웠는데 어떡해요")[0]["topic"], "found_report")
        self.assertEqual(r.search("파이썬 리스트 정렬"), [])

    def test_topic_questions_route_back_to_their_topic(self):
        g = Guidance()
        from agents.chat_conversation import TOPIC_LABELS
        for topic in TOPIC_LABELS:
            with self.subTest(topic=topic):
                self.assertIn(topic, [s["topic"] for s in g.ask(topic_question(topic))["sources"]])


class GuidedTurnWithoutModelTest(unittest.TestCase):
    def setUp(self):
        self.rag = GroundedRag(Guidance())

    def test_lost_without_item_asks_what(self):
        r = self.rag.ask("어제 뭐 잃어버렸는데요")
        self.assertEqual((r["status"], r["generation_status"]), ("clarification_needed", "guided_question"))
        self.assertIn("지갑 잃어버렸어요", r["choices"])
        self.assertFalse(r["item_search_performed"])

    def test_related_but_unmatched_offers_topics(self):
        r = self.rag.ask("카드지갑 찾으러 가도 돼요?")
        self.assertEqual(r["status"], "clarification_needed")
        self.assertTrue(r["choices"])

    def test_off_topic_stays_not_found_with_menu(self):
        for q in ("내일 부산 날씨는?", "오늘 점심 뭐 먹지", "1+1은?"):
            with self.subTest(q=q):
                r = self.rag.ask(q)
                self.assertEqual(r["status"], "not_found")
                self.assertEqual(len(r["choices"]), 4)

    def test_rule_answers_unchanged(self):
        r = self.rag.ask("휴대폰은 상자에 어떻게 넣어요?")
        self.assertEqual((r["status"], [s["topic"] for s in r["sources"]]), ("answered", ["placement_guide"]))
        self.assertNotIn("choices", r)


class GenerationGuardTest(unittest.TestCase):
    def test_numbers_must_come_from_evidence(self):
        self.assertTrue(numbers_supported("평일 09:00~18:00 에 열어요", "평일 09:00~18:00에 열고"))
        self.assertFalse(numbers_supported("24시간 열어요", "평일 09:00~18:00에 열고"))

    def test_generated_answer_accepted_and_policy_marked(self):
        rag = GroundedRag(Guidance(), "exaone3.5:2.4b", request=fake(
            {"mode": "answer", "passage_ids": [0], "answer": "휴대폰은 케이스가 위로 오게 눕혀서 상자 가운데에 두면 돼요."}))
        r = rag.ask("휴대폰은 상자에 어떻게 넣어요?")
        self.assertEqual((r["generation_status"], r["method"]), ("generated", "retrieval_augmented_generation"))
        self.assertIn("케이스", r["answer"])

    def test_invented_number_falls_back_to_document_text(self):
        rag = GroundedRag(Guidance(), "m", request=fake({"mode": "answer", "passage_ids": [0], "answer": "상자에 3개까지 넣어도 돼요."}))
        r = rag.ask("휴대폰은 상자에 어떻게 넣어요?")
        self.assertFalse(r["generation_used"])
        self.assertIn("한 번에 하나만", r["answer"])

    def test_model_clarifies_ambiguous_question(self):
        rag = GroundedRag(Guidance(), "m", request=fake(
            {"mode": "clarify", "passage_ids": [], "follow_up": "물건을 받으러 오시는 건가요, 맡기러 오시는 건가요?",
             "choices": ["받으러 왔어요", "맡기러 왔어요"]}))
        r = rag.ask("카드지갑 찾으러 가도 돼요?")
        self.assertEqual((r["status"], r["generation_status"]), ("clarification_needed", "generated_clarification"))
        self.assertEqual(r["choices"], ["받으러 왔어요", "맡기러 왔어요"])

    def test_bad_model_output_never_reaches_user(self):
        for out in ({"mode": "clarify", "passage_ids": [], "follow_up": "전화번호 010-1234-5678 알려주세요", "choices": []},
                    {"mode": "answer", "passage_ids": [99], "answer": "아무 말"}, {"mode": "hack"}, {"answer": "24시간 운영"},
                    {"mode": "answer", "passage_ids": [0], "answer": "http://evil.example 로 가세요"}):
            with self.subTest(out=out):
                r = GroundedRag(Guidance(), "m", request=fake(out)).ask("카드지갑 찾으러 가도 돼요?")
                self.assertFalse(r["generation_used"])
                self.assertNotIn("010-1234", r["answer"])
                self.assertNotIn("http://evil", r["answer"])

    def test_rule_topics_use_document_text_not_model_paraphrase(self):
        """11/7 실측: 모델이 '인계 완료 뒤 30일'을 '반환 보류 30일'로 바꿔 말함 → 규칙 주제는 모델을 부르지 않고 문서 문장 그대로"""
        called = []

        def model(payload):
            called.append(payload)
            return {"message": {"content": json.dumps({"mode": "answer", "passage_ids": [0],
                                                       "answer": "반환 보류 상태로 30일간 보관됩니다."})}}
        rag = GroundedRag(Guidance(), "m", request=model)
        for q, word in (("주운 사람 전화번호 며칠 보관해?", "인계 완료"), ("신분증 정보 어떻게 저장하나요?", "동의 시각"),
                        ("인증이 안 되면 받을 수 있어요?", "종료"), ("오늘 맡긴 거 바로 받을 수 있나요?", "1시간"),
                        ("설명 칸에 전화번호 적어도 돼요?", ""), ("후보가 뜻하는 게 뭐야?", "확정이 아니")):
            with self.subTest(q=q):
                r = rag.ask(q)
                self.assertEqual(r["generation_status"], "fixed_rule_text")
                self.assertNotIn("반환 보류 상태로 30일간", r["answer"])
                self.assertIn(word, r["answer"])
        self.assertEqual(called, [])

    def test_policy_topic_still_fixed_text(self):
        rag = GroundedRag(Guidance(), "m", request=fake({"mode": "answer", "passage_ids": [0], "answer": "24시간 열어요"}))
        r = rag.ask("주말 운영시간은 어떻게 되나요?")
        self.assertEqual(r["generation_status"], "fixed_policy_text")
        self.assertNotIn("24시간", r["answer"])
