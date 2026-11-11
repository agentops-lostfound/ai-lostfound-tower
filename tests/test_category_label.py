"""11/8 품목 화면 이름: '모형폰' → '휴대폰'(사람에게 보이는 글만).

한줄 설명: 저장·계약 값은 '모형폰' 그대로 두고(비전·매칭·로봇 코드 영향 없음), 화면·디스코드·챗봇 문장만 '휴대폰'으로 보인다.
           사용자가 '모형폰'이라고 써도, '휴대폰'이라고 써도 똑같이 알아듣는다.
"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import CATEGORIES, MVP_CATEGORIES, category_label, show_ko  # noqa: E402

ENV = {"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}


def strings(o):
    """응답 안의 글자 값을 모두 꺼낸다(키 이름 제외)"""
    if isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, (list, tuple)):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


class LabelTest(unittest.TestCase):
    def test_contract_values_stay(self):
        self.assertIn("모형폰", CATEGORIES)                    # 계약 값은 그대로(팀원 코드 영향 없음)
        self.assertIn("모형폰", MVP_CATEGORIES)
        self.assertNotIn("휴대폰", CATEGORIES)

    def test_label(self):
        self.assertEqual(category_label("모형폰"), "휴대폰")
        self.assertEqual(category_label("지갑"), "카드지갑")       # 11/10: 저장 값은 지갑, 보이는 이름은 카드지갑
        self.assertEqual(category_label(None), "")
        self.assertEqual(show_ko("모형폰"), "휴대폰")
        self.assertEqual(show_ko("rectangular, plastic"), "직사각형, 플라스틱")


class SimDemoTextTest(unittest.TestCase):
    def setUp(self):
        from agents.sim_director import build_sim_service
        self.svc = build_sim_service(ENV)
        self.d = self.svc.sim
        # 11/9: 시작 때 휴대폰 칸(R1) 2개가 차 있어 습득 휴대폰은 칸 대기가 된다 → R1-1 시연 물건을 직원 보관 선반으로 옮겨 칸 하나를 비움
        self.svc.move_to_shelf({"item_id": self.svc.world.slot_id_of and next(
            r["item_id"] for r in self.svc.world.items.values() if self.svc.world.slot_id_of(r["item_id"]) == "R1-1")})

    def run_lost(self, text):
        r = self.d.lost(text)
        if "pending_id" in r:                                   # 후보가 여러 개면 역을 묻는다
            r = self.d.answer(r["pending_id"], "중앙")
        self.assertTrue(self.d.wait_idle())
        return r

    def check_story(self, phrase_found, phrase_lost):
        f = self.d.found(phrase_found)
        self.assertTrue(self.d.wait_idle())
        self.assertNotIn("모형폰", f["features"])
        self.assertIn("휴대폰", f["features"])
        r = self.run_lost(phrase_lost)
        self.assertEqual(r["item_id"], f["item_id"])
        self.assertEqual(self.svc.world.items[r["item_id"]]["category"], "모형폰")    # 저장 값은 그대로
        for c in r["candidates"]:
            self.assertNotIn("모형폰", c["card"])
        st = self.svc.board.story(r["story_id"])
        self.assertTrue(st["result"]["ok"], st["result"])
        self.assertIn("휴대폰", st["title"])
        shown = [st["title"], *[s.get("detail") or "" for s in st["stages"]],
                 *[e.get("body") or "" for e in self.svc.board.since(0)], *[e.get("title") or "" for e in self.svc.board.since(0)]]
        self.assertFalse([t for t in shown if "모형폰" in t], shown)

    def test_found_model_word_lost_phone_word(self):
        self.check_story("중앙역 3번 출구에서 빨간 모형폰 주웠어요", "빨간 휴대폰 잃어버렸어요")   # 파랑은 보관함 시연 물건과 닮아 직원 확인으로 감

    def test_found_phone_word_lost_model_word(self):
        self.check_story("중앙역 3번 출구에서 빨간 휴대폰 주웠어요", "빨간 모형폰 잃어버렸어요")

    def test_unknown_item_message_says_phone(self):
        from agents.service import RequestError
        with self.assertRaises(RequestError) as e:
            self.d.lost("우산 잃어버렸어요")
        self.assertIn("휴대폰", str(e.exception))
        self.assertNotIn("모형폰", str(e.exception))


class ChatTextTest(unittest.TestCase):
    def setUp(self):
        from agents.chat_rag import GroundedRag
        from agents.guidance import Guidance
        self.rag = GroundedRag(Guidance(), None)

    def test_lost_both_words(self):
        for q in ("휴대폰 잃어버렸어요", "모형폰 잃어버렸어요"):
            r = self.rag.ask(q)
            self.assertEqual(r["status"], "answered", q)
            self.assertIn("휴대폰 분실로 이해했어요", r["answer"], q)
            self.assertNotIn("모형폰", r["answer"], q)

    def test_categories_question_both_words(self):
        for q in ("휴대폰도 찾을 수 있어요?", "모형폰도 찾을 수 있어요?"):
            r = self.rag.ask(q)
            self.assertEqual([s["topic"] for s in r["sources"]], ["categories"], q)
            self.assertIn("휴대폰", r["answer"], q)
            self.assertNotIn("모형폰", r["answer"], q)

    def test_search_both_words(self):
        from agents.chat_search import SearchAgent, SimTowerItemSearch
        from agents.sim_director import build_sim_service
        svc = build_sim_service(ENV)
        agent = SearchAgent(SimTowerItemSearch(svc.world.chat_items))
        for q in ("파란 휴대폰 찾아줘", "파란 모형폰 찾아줘"):
            out = agent.ask(q)
            self.assertEqual(out["status"], "items_found", q)
            self.assertEqual([c["category"] for c in out["candidates"]], ["모형폰"])   # JSON 값은 그대로(화면이 바꿔 보임)
            self.assertIn("찾은 조건: 휴대폰", out["answer"])
            self.assertNotIn("모형폰", out["answer"])
        self.assertNotIn("모형폰", agent.ask("우산 찾아줘")["answer"])

    def test_statistics_answer(self):
        from center.statistics import KST, count_response, plan_count
        for word in ("휴대폰", "모형폰"):
            q = plan_count(f"오늘 등록기계 A에 들어온 {word} 몇 개?", now=datetime(2026, 11, 8, 12, tzinfo=KST))
            self.assertEqual(q.category, "모형폰")                              # SQL 값은 그대로
            out = count_response(q, 2, q.sql, q.params, "s", "m")
            self.assertIn("휴대폰 접수는 2건", out["answer"])


class StorageTextTest(unittest.TestCase):
    def test_wrong_row_message(self):
        from agents.storage import StorageError, _category_ok
        with self.assertRaises(StorageError) as e:
            _category_ok({"code": "R1", "kind": "shelf", "allowed_categories": ["모형폰"]}, "지갑", False)
        self.assertIn("휴대폰 자리", str(e.exception))
        self.assertNotIn("모형폰", str(e.exception))


if __name__ == "__main__":
    unittest.main()
