"""11/9 사용자 요청 시험 — ① 관제탑에서 물건의 습득 역 보이기 ② '폰' 낱말 알아듣기(이어폰·헤드폰 제외)
③ 습득·분실 버튼을 바꿔 누른 경우 안내. 시간 배수 0 으로 기다리지 않는다."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_agents import ITEM_WORDS  # noqa: E402
from agents.chat_rag import items_named  # noqa: E402
from agents.contracts import mentions_phone, station_name  # noqa: E402
from agents.lost_input import text_features  # noqa: E402
from agents.service import RequestError  # noqa: E402
from agents.sim_director import TO_FOUND, TO_LOST, build_sim_service  # noqa: E402
from agents.sim_world import SimWorld, query_features, sim_qwen  # noqa: E402
from center.statistics import plan_count  # noqa: E402

ENV = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}
PHONE_SAYS = ["파란색 폰 잃어버렸어요", "핸드폰", "휴대폰", "휴대전화", "스마트폰", "전화기", "아이폰", "갤럭시 S24", "모형폰", "폰을 두고 내렸어요"]
NOT_PHONE_SAYS = ["이어폰 잃어버렸어요", "헤드폰", "에어팟", "갤럭시 버즈", "무선 이어폰", "블루투스 헤드폰", "폰트"]


class PhoneWordsTest(unittest.TestCase):
    def test_phone_words_are_phone(self):
        for t in PHONE_SAYS:
            with self.subTest(t=t):
                self.assertTrue(mentions_phone(t))
                self.assertEqual(sim_qwen(t)["category"], "phone")            # 가상 시연(디스코드·/live 시험 입력)
                self.assertEqual(query_features(t).get("category"), "모형폰")
                self.assertEqual(text_features(t)[0]["category"], "모형폰")     # 분실인 웹·챗봇 검색
                self.assertEqual(items_named(t), {"모형폰"})                   # 챗봇 답 검사
                self.assertTrue(ITEM_WORDS.search(t))                          # 챗봇 물건 검색 허용 신호

    def test_earphones_are_not_phone(self):
        for t in NOT_PHONE_SAYS:
            with self.subTest(t=t):
                self.assertFalse(mentions_phone(t))
                self.assertEqual(sim_qwen(t)["category"], "unknown")
                self.assertNotIn("category", query_features(t))
                self.assertNotEqual(text_features(t)[0]["category"], "모형폰")
                self.assertEqual(items_named(t), set())

    def test_other_items_still_win(self):
        self.assertEqual(sim_qwen("검정 카드지갑 주웠어요")["category"], "card_wallet")
        self.assertEqual(text_features("이어폰이랑 같이 넣어 둔 검정 지갑")[0].get("category"), "지갑")

    def test_statistics_phone_question(self):
        self.assertEqual(plan_count("오늘 들어온 폰 몇 개").category, "모형폰")
        self.assertEqual(plan_count("오늘 들어온 아이폰 몇 개").category, "모형폰")
        with self.assertRaises(ValueError):                                    # 이어폰은 품목이 아님 → 전체 수로 바꿔 세지 않음
            plan_count("오늘 들어온 이어폰 몇 개")


class StationTest(unittest.TestCase):
    def test_station_name_rule(self):
        self.assertEqual(station_name("KIOSK-A"), "중앙역")
        self.assertEqual(station_name("KIOSK-C"), "초량역")
        self.assertEqual(station_name("CENTER"), "부산역 본센터")
        self.assertEqual(station_name(None, "S-20261109-0003"), "초량역")      # 실제 DB 모드: 물건 번호 앞글자
        self.assertEqual(station_name(None, "A-W01"), "중앙역")
        self.assertEqual(station_name(None, "H-20261109-0001"), "부산역 본센터")
        self.assertEqual(station_name(None, "C-20261109-0001"), "")            # 찾기 번호(C-)는 역이 아님
        self.assertEqual(station_name(None, None), "")

    def test_snapshot_has_station(self):
        w = SimWorld(speed=0, seed=False)
        a = w.create({"machine_id": "KIOSK-A", "place_text": "중앙역", "finder": None})
        s = w.create({"machine_id": "KIOSK-C", "place_text": "초량역", "finder": None})
        items = {i["item_id"]: i for i in w.snapshot()["items"]}
        self.assertEqual(items[a["item_id"]]["station"], "중앙역")
        self.assertEqual(items[s["item_id"]]["station"], "초량역")
        self.assertTrue(all("station" in i for i in w.snapshot()["items"]))


class WrongButtonTest(unittest.TestCase):
    def setUp(self):
        self.svc = build_sim_service(ENV)
        self.d = self.svc.sim

    def test_lost_words_on_found_button(self):
        for t in ("파란색 폰 잃어버렸어요", "파란색 폰 잃어버렸어요. 초량역", "초량역에서 지갑 분실했어요"):
            with self.subTest(t=t), self.assertRaises(RequestError) as e:
                self.d.found(t)
            self.assertEqual(str(e.exception), TO_LOST)

    def test_found_words_on_lost_button(self):
        for t in ("초량역에서 파란색 폰 주웠어요", "중앙역 화장실에 지갑이 떨어져 있었어요"):
            with self.subTest(t=t), self.assertRaises(RequestError) as e:
                self.d.lost(t)
            self.assertEqual(str(e.exception), TO_FOUND)

    def test_right_buttons_still_work(self):
        r = self.d.found("초량역 5번 출구 앞에서 파란색 폰 주웠어요")
        self.assertTrue(self.d.wait_idle())
        self.assertTrue(r["item_id"].startswith("S-"))
        self.assertEqual(self.d.world.items[r["item_id"]]["category"], "모형폰")
        out = self.d.lost("파란색 폰 잃어버렸어요. 초량역")                      # 사용자 실측 문장 → 분실 신고가 됨
        self.assertTrue(self.d.wait_idle())
        self.assertTrue(out.get("claim_id") or out.get("pending_id") or out.get("staff"))


if __name__ == "__main__":
    unittest.main()


class PhoneDirectionTest(unittest.TestCase):
    """11/9 09:51 사용자 결정: R1 휴대폰은 탑뷰 '/' 45도 — 상단(카메라) 오른쪽 위 · 단자 왼쪽 아래"""
    def test_live_draws_phone_slash(self):
        from pathlib import Path
        html = (Path(__file__).resolve().parent.parent / "web/live/index.html").read_text(encoding="utf-8")
        self.assertNotIn("rotate(-45)", html)                    # '\' 방향(예전)이 남아 있지 않음
        self.assertGreaterEqual(html.count("rotate(45)"), 3)     # 칸 자리 · 보관된 휴대폰 · 범례
        from agents.storage import LAYOUT
        self.assertEqual(next(r for r in LAYOUT if r[0] == "R1")[5], "45도 사선·상단 오른쪽 위")
