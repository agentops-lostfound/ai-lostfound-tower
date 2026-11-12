"""11/12 [📦 보관함 채우기] — 실물 보관함 배치 8칸(R4-2 파란 립밤 포함)으로 화면·DB 를 채운다. [처음으로]는 그대로 빈 보관함"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WANT = {"R1-1": ("모형폰", "검정"), "R1-2": ("모형폰", "흰색"), "R2-1": ("보조배터리", "흰색"), "R2-2": ("보조배터리", "검정"),
        "R3-1": ("핸드크림", "분홍"), "R3-2": ("핸드크림", "파랑"), "R4-1": ("립밤", "빨강"), "R4-2": ("립밤", "파랑")}


class LayoutSeedTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from agents.api import build_app
            from agents.sim_director import build_sim_service
        except ImportError:
            self.skipTest("fastapi 필요")
        self.svc = build_sim_service({"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_AGENT_TALK": "0"})
        self.c = TestClient(build_app(self.svc))

    def slots(self):
        w = self.svc.sim.world
        return {w.slot_id_of(i): (r.get("category"), (r.get("features") or {}).get("color")) for i, r in w.items.items()}

    def test_layout_then_reset_empty(self):
        self.assertEqual(self.slots(), {})                                   # 기본: 빈 보관함
        r = self.c.post("/sim/reset", json={"seed": "layout"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.slots(), WANT)
        self.assertEqual(self.c.post("/sim/reset", json={}).status_code, 200)
        self.assertEqual(self.slots(), {})                                   # [처음으로]는 다시 빈 보관함
        self.assertEqual(self.c.post("/sim/reset", json={"seed": "../x"}).status_code, 422)

    def test_refuses_when_item_on_workbench(self):
        """11/12 안전: 작업대(제출보관함·집게)·회수 중 물건이 있거나 로봇팔이 쥐고 있으면 기본 세팅을 하지 않음(409)"""
        from agents.sim_world import LOC_BASKET, LOC_GRIPPER
        w = self.svc.sim.world
        self.c.post("/sim/reset", json={"seed": "layout"})
        iid = next(iter(w.items))
        for loc, word in ((LOC_BASKET, "제출보관함"), (LOC_GRIPPER, "집게")):
            w.items[iid]["loc"] = loc
            r = self.c.post("/sim/reset", json={"seed": "layout"})
            self.assertEqual(r.status_code, 409, r.text)
            self.assertIn(word, r.text)
            self.assertIn(iid, w.items)                                     # 거절하면 아무것도 지우지 않음
        w.items[iid]["loc"] = "bin"
        w.arm["holding"] = iid
        self.assertEqual(self.c.post("/sim/reset", json={"seed": "layout"}).status_code, 409)
        w.arm["holding"] = None
        self.assertEqual(self.c.post("/sim/reset", json={"seed": "layout"}).status_code, 200)

    def test_button_on_showcase(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        html = open(os.path.join(root, "web", "showcase", "index.html"), encoding="utf-8").read()
        for needle in ('id="btnSeed"', '{seed: "layout", force_real: robotControl}', '$("btnSeed").hidden = !d.sim;'):
            self.assertIn(needle, html)


if __name__ == "__main__":
    unittest.main()
