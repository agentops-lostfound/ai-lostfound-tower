"""11/7 챗봇 ↔ 가상 시연 관제탑 연결(LF-5 변재원).

한줄 설명: 화면 작업대에 파란 모형폰이 있는데 챗봇이 "후보 없음"이라고 답하던 허점(연습용 별도 목록을 찾았음)과,
"해운대역에서 어제 잃어버렸어요"처럼 장소·날짜만 덧붙이면 앞에서 말한 물건을 잊던 허점을 고쳤는지 확인한다.
- langgraph·langsmith 가 없으면 test_chat_color_multiturn.py 와 같은 작은 대역을 끼운다
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_chat_color_multiturn import setUpModule, tearDownModule  # noqa: E402,F401

ENV = {"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}


class SimTowerSearchTest(unittest.TestCase):
    def setUp(self):
        from agents.chat_search import SearchAgent, SimTowerItemSearch
        from agents.sim_director import build_sim_service
        self.svc = build_sim_service(ENV)
        self.db = SimTowerItemSearch(self.svc.world.chat_items)
        self.agent = SearchAgent(self.db)

    def test_finds_the_blue_phone_on_the_board(self):
        out = self.agent.ask("파란색 휴대폰을 잃어버렸어")
        self.assertEqual(out["status"], "items_found")                       # 인증 없이(가짜 물건만)
        self.assertEqual([(c["category"], c["color"]) for c in out["candidates"]], [("모형폰", "파랑")])
        self.assertIn("가상 시연 관제탑", out["answer"])
        self.assertIn("잃어버린 물건 찾기", out["answer"])                   # 다음 행동 안내
        self.assertNotIn("H-2026", out["answer"])                            # 물건 번호는 답에 드러내지 않음

    def test_station_falls_back_and_says_so(self):
        out = self.agent.ask("해운대역에서 파란 휴대폰 잃어버렸어요")         # 시연 물건은 본센터 접수 → 역 조건 없이 다시
        self.assertEqual(out["status"], "items_found")
        self.assertIn("입력한 역 우선, 없으면 모든 역", out["answer"])

    def test_only_items_still_in_storage(self):
        iid = next(r["item_id"] for r in self.svc.world.items.values() if r["features"].get("color") == "파랑")
        self.svc.world.db_set_status(iid, "인계 완료")
        self.assertEqual(self.agent.ask("파란 휴대폰 찾아줘")["status"], "items_not_found")
        self.assertEqual(self.db.search("모형폰", "흰색", {"lost_date": "2999-01-01"}), [])   # 분실 날짜 이후 접수만

    def test_chat_items_hide_private_features(self):
        for r in self.svc.world.chat_items():
            self.assertEqual(set(r["features"]), {"color"})
            self.assertNotIn("private_features", r)


class FollowUpPlaceTest(unittest.TestCase):
    def setUp(self):
        from agents.guidance import Guidance
        self.guide = Guidance()

    def resolve(self, q, history):
        from agents.chat_conversation import resolve_turn
        return resolve_turn(q, history, {}, self.guide)

    def test_place_and_date_continue_previous_item(self):
        q, ctx, resolved = self.resolve("해운대역에서 어제 잃어버렸어요", ["파란색 휴대폰을 잃어버렸어"])
        self.assertTrue(resolved)
        self.assertEqual((ctx["category"], ctx["color"]), ("모형폰", "파랑"))
        self.assertTrue(q.endswith("찾아줘"))

    def test_how_to_and_new_item_stay_independent(self):
        self.assertFalse(self.resolve("어제 운영시간 어떻게 돼요?", ["파란색 휴대폰을 잃어버렸어"])[2])
        self.assertFalse(self.resolve("해운대역에서 지갑을 주웠는데 어디에 맡겨요?", ["파란색 휴대폰을 잃어버렸어"])[2])
        self.assertFalse(self.resolve("해운대역에서 어제 잃어버렸어요", [])[2])          # 앞 물건이 없으면 이어받지 않음


class SimAppChatTest(unittest.TestCase):
    def test_tower_app_chat_uses_sim_items(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.api import build_app
        from agents.sim_director import build_sim_service
        c = TestClient(build_app(build_sim_service(ENV)))
        first = c.post("/chat/questions", json={"question": "파란색 휴대폰을 잃어버렸어"}).json()
        self.assertEqual(first["status"], "items_found", first)
        follow = c.post("/chat/questions", json={"question": "해운대역에서 어제 잃어버렸어요",
                                                  "history": ["파란색 휴대폰을 잃어버렸어"]}).json()
        self.assertEqual(follow["status"], "items_found", follow)
        self.assertTrue(follow["context_used"])


if __name__ == "__main__":
    unittest.main()
