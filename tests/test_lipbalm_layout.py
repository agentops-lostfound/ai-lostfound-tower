"""11/11 사용자 결정: 운영 품목 카드지갑 → 립밤(포토박스 탑뷰가 카드지갑을 잘 못 알아봄).

1) 처음 보관함은 비어 있음(11/11 오후). 분홍 핸드크림 하나는 TOWER_SIM_SEED=cream, 예전 5개는 full(그 안의 카드지갑도 빨간 립밤으로)
2) 보관함 열: 왼쪽부터 휴대폰 · 보조배터리 · 핸드크림 · 립밤 (마이그레이션 020)
3) '지갑'은 운영하지 않는 품목 안내로(11/10 의 '카드지갑' 유도 한 줄은 이제 붙이지 않음). 옛 기록 값 '지갑'은 그대로 읽힘
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ENV = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}


class SeedTest(unittest.TestCase):
    def test_default_seed_is_empty(self):
        # 11/11 사용자 결정: 실물 시연 기본 → 처음 보관함은 비어 있음(켤 때마다 더미 크림이 다시 생기지 않음)
        from agents.sim_director import build_sim_service
        for env in (ENV, {**ENV, "TOWER_SIM_SEED": "none"}, {**ENV, "TOWER_SIM_SEED": "모름"}):
            svc = build_sim_service(env)
            self.assertEqual(svc.world.items, {})
            self.assertEqual([s for sec in svc.storage.layout()["sections"] for s in sec["slots"] if s.get("item")], [])
            svc.sim.reset()
            self.assertEqual(svc.world.items, {})                          # [전체 초기화] 뒤에도 비어 있음

    def test_cream_seed_is_one_pink_hand_cream_in_r3(self):
        from agents.sim_director import build_sim_service
        svc = build_sim_service({**ENV, "TOWER_SIM_SEED": "cream"})
        items = list(svc.world.items.values())
        self.assertEqual([(r["category"], r["features"]["color"]) for r in items], [("핸드크림", "분홍")])
        self.assertEqual(svc.world.slot_id_of(items[0]["item_id"]), "R3-1")

    def test_full_seed_has_red_lipbalm_not_wallet(self):
        from agents.sim_director import build_sim_service
        items = list(build_sim_service({**ENV, "TOWER_SIM_SEED": "full"}).world.items.values())
        self.assertEqual(len(items), 5)
        cats = [(r["category"], r["features"]["color"]) for r in items]
        self.assertIn(("립밤", "빨강"), cats)
        self.assertNotIn("지갑", [c for c, _ in cats])

    def test_every_category_gets_a_slot_right_after_start(self):
        from agents.sim_director import build_sim_service
        from agents.storage import recommend_slot
        lay = build_sim_service(ENV).storage.layout()
        got = {c: recommend_slot(lay, c)["slot_id"] for c in ("모형폰", "보조배터리", "핸드크림", "립밤")}
        self.assertEqual(got, {"모형폰": "R1-1", "보조배터리": "R2-1", "핸드크림": "R3-1", "립밤": "R4-1"})   # 빈 보관함: 먼 줄(-1)부터
        self.assertIsNone(recommend_slot(lay, "지갑"))           # 카드지갑은 받는 열이 없음 → 직원 보관 선반


class ColumnOrderTest(unittest.TestCase):
    def test_left_to_right(self):
        from agents.storage import LAYOUT
        rows = [(code, label, allowed) for code, label, kind, allowed, *_ in LAYOUT if kind == "shelf"]
        self.assertEqual(rows, [("R1", "R1 휴대폰 전용", ["모형폰"]), ("R2", "R2 보조배터리", ["보조배터리"]),
                                ("R3", "R3 핸드크림", ["핸드크림"]), ("R4", "R4 립밤", ["립밤"])])

    def test_active_categories(self):
        from agents.contracts import ACTIVE_CATEGORIES, CATEGORIES, category_label, is_active_category
        self.assertEqual(ACTIVE_CATEGORIES, ["모형폰", "보조배터리", "핸드크림", "립밤"])
        self.assertIn("지갑", CATEGORIES)                         # 옛 기록·비전 결과가 '목록에 없는 값'으로 거절되지 않게
        self.assertFalse(is_active_category("카드지갑"))
        self.assertEqual(category_label("지갑"), "카드지갑")      # 옛 기록은 예전 이름으로 보임

    def test_migration_020_moves_r4_from_wallet_to_lipbalm(self):
        sql = (Path(ROOT) / "center" / "migrations" / "020_column_r4_lipbalm_1111.sql").read_text(encoding="utf-8")
        body = "\n".join(l for l in sql.splitlines() if not l.lstrip().startswith("--"))
        self.assertIn("SET label = 'R4 립밤', allowed_categories = '{립밤}'", body)
        self.assertIn("WHERE section_code = 'R4' AND allowed_categories = '{지갑}'", body)   # 018 값 그대로일 때만


class WalletIsRetiredTest(unittest.TestCase):
    def test_nudge_is_off(self):
        from agents.chatbot import wallet_nudge
        out = {"status": "items_found", "agent": "search", "answer": "후보 1개를 찾았어요."}
        self.assertEqual(wallet_nudge("검정 지갑 찾아줘", None, out), out)

    def test_chatbot_says_wallet_is_not_handled(self):
        import tempfile
        from agents.chat_search import DemoItemDatabase, SearchAgent
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        r = Chatbot(Guidance(), search=SearchAgent(DemoItemDatabase(Path(tmp.name) / "demo.sqlite3"))).ask("검정 카드지갑 찾아줘")
        self.assertIn("운영하지 않는 품목", r["answer"])
        self.assertIn("립밤", r["answer"])

    def test_screens_offer_lipbalm(self):
        web = Path(ROOT) / "web"
        self.assertIn("const CATS = ['모형폰','보조배터리','핸드크림','립밤'];", (web / "kiosk" / "index.html").read_text(encoding="utf-8"))
        self.assertIn('data-v="립밤"', (web / "lost" / "index.html").read_text(encoding="utf-8"))
        self.assertNotIn('data-v="지갑"', (web / "lost" / "index.html").read_text(encoding="utf-8"))
        live = (web / "live" / "index.html").read_text(encoding="utf-8")
        self.assertIn('"립밤": {rot: 0', live)                   # 립밤은 세로
        self.assertIn('"핸드크림": {rot: 45, w: 26, h: 72, cap: 16}', live)   # 핸드크림은 '/' + 뚜껑(왼쪽 아래 끝)
        self.assertIn('"보조배터리": {rot: 45', live)


if __name__ == "__main__":
    unittest.main()
