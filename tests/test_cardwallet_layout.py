"""11/10 사용자 결정 세 가지를 한곳에서 지킨다.

1) 처음 보관된 가상 물건은 분홍 핸드크림 하나(예전 5개 묶음은 TOWER_SIM_SEED=full)
2) 보관함 열: 왼쪽부터 휴대폰 · 보조배터리 · 핸드크림 · 카드지갑
3) 품목 이름은 '카드지갑'(저장 값은 '지갑' 그대로). 챗봇은 '지갑'을 알아듣고 답에 한 줄을 덧붙여 '카드지갑'으로 이끈다
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ENV = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}


class SeedTest(unittest.TestCase):
    def test_default_seed_is_one_pink_hand_cream_in_r3(self):
        from agents.sim_director import build_sim_service
        svc = build_sim_service(ENV)
        items = list(svc.world.items.values())
        self.assertEqual([(r["category"], r["features"]["color"]) for r in items], [("핸드크림", "분홍")])
        self.assertEqual(svc.world.slot_id_of(items[0]["item_id"]), "R3-1")
        used = [s["slot_id"] for sec in svc.storage.layout()["sections"] for s in sec["slots"] if s.get("item")]
        self.assertEqual(used, ["R3-1"])                      # 다른 칸은 모두 비어 있음 → 4종 모두 바로 보관됨

    def test_full_seed_only_when_asked(self):
        from agents.sim_director import build_sim_service
        self.assertEqual(len(build_sim_service({**ENV, "TOWER_SIM_SEED": "full"}).world.items), 5)
        self.assertEqual(len(build_sim_service({**ENV, "TOWER_SIM_SEED": "엉뚱한값"}).world.items), 1)

    def test_every_category_gets_a_slot_right_after_start(self):
        """예전에는 휴대폰 칸 2개가 시작부터 차 있어 습득 휴대폰이 '본센터로 회수'에서 멈췄다(11/10)"""
        from agents.sim_director import build_sim_service
        from agents.storage import recommend_slot
        lay = build_sim_service(ENV).storage.layout()
        got = {c: recommend_slot(lay, c)["slot_id"] for c in ("모형폰", "보조배터리", "핸드크림", "지갑")}
        self.assertEqual(got, {"모형폰": "R1-1", "보조배터리": "R2-1", "핸드크림": "R3-2", "지갑": "R4-1"})


class ColumnOrderTest(unittest.TestCase):
    def test_left_to_right(self):
        from agents.storage import LAYOUT
        rows = [(code, label, allowed) for code, label, kind, allowed, *_ in LAYOUT if kind == "shelf"]
        self.assertEqual(rows, [("R1", "R1 휴대폰 전용", ["모형폰"]), ("R2", "R2 보조배터리", ["보조배터리"]),
                                ("R3", "R3 핸드크림", ["핸드크림"]), ("R4", "R4 카드지갑", ["지갑"])])

    def test_label_is_card_wallet_value_stays(self):
        from agents.contracts import ACTIVE_CATEGORIES, category_label
        self.assertIn("지갑", ACTIVE_CATEGORIES)               # DB·비전·매칭 값은 그대로
        self.assertEqual(category_label("지갑"), "카드지갑")


class WalletNudgeTest(unittest.TestCase):
    def nudge(self, q, out, history=None):
        from agents.chatbot import wallet_nudge
        return wallet_nudge(q, history, out)

    def test_plain_wallet_is_led_to_card_wallet_once(self):
        from agents.chatbot import WALLET_NUDGE
        out = {"status": "items_found", "agent": "search", "answer": "후보 1개를 찾았어요."}
        got = self.nudge("검정 지갑 찾아줘", out)
        self.assertEqual(got["answer"], "후보 1개를 찾았어요.\n" + WALLET_NUDGE)       # 핵심(후보 수)이 먼저, 유도는 끝에
        ask = {"status": "intake", "agent": "intake", "answer": "지금까지: 물건 카드지갑. 물건 색이 무엇인가요?"}
        self.assertTrue(self.nudge("지갑 잃어버렸어요 접수해 주세요", ask)["answer"].startswith(WALLET_NUDGE))   # 접수 대화는 질문이 끝에 남게 앞에
        self.assertEqual(out["answer"], "후보 1개를 찾았어요.")                       # 원래 답은 건드리지 않음
        self.assertTrue(self.nudge("지깝 일어버림", out)["answer"].endswith(WALLET_NUDGE))     # 오타도
        self.assertEqual(self.nudge("갈색이요", out, ["검정 지갑 찾아줘"]), out)       # 이어 묻기에는 다시 말하지 않음
        self.assertEqual(self.nudge("갈색 지갑은요", out, ["검정 지갑 찾아줘"]), out)

    def test_not_added_when_not_needed(self):
        out = {"status": "items_found", "agent": "search", "answer": "후보 1개를 찾았어요."}
        for q in ("검정 카드지갑 찾아줘", "카드 지갑 잃어버렸어요", "파란 휴대폰 찾아줘", ""):
            self.assertEqual(self.nudge(q, out), out, q)
        lost = {"status": "not_found", "agent": "guidance", "answer": "질문을 정확히 이해하지 못했어요."}
        self.assertEqual(self.nudge("오늘 지갑 반환 실패 원인", lost), lost)           # 못 알아들은 답
        ops = {"status": "answered", "agent": "ops", "answer": "반환 실패 2건"}
        self.assertEqual(self.nudge("지갑 반환 실패 원인", ops), ops)                  # 직원 관제 답
        self.assertEqual(self.nudge("지갑", None), None)
        self.assertEqual(self.nudge("지갑", {"agent": "search"}), {"agent": "search"})

    def test_guidance_answer_that_names_card_wallet(self):
        from agents.chatbot import WALLET_NUDGE
        out = {"status": "answered", "agent": "guidance", "answer": "카드지갑 분실로 이해했어요."}
        self.assertTrue(self.nudge("지갑을 잃어버렸어요", out)["answer"].endswith(WALLET_NUDGE))


if __name__ == "__main__":
    unittest.main()
