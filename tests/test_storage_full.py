"""11/9 보관 칸 규칙(015·016 열 배정: 휴대폰 R1 · 카드지갑 R2 · 보조배터리 R3 · 핸드크림 R4)과 보관함이 꽉 찼을 때(칸 대기 → 자동 회수, 직원 보관 선반) 시험.

가상 시연(TOWER_SIM=1)은 시간 배수 0 으로 기다리지 않는다. 뒤에서 도는 회수는 조건이 맞을 때까지 잠깐 기다린다(until).
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import DECISION_REJECTED, DECISION_RETURNED, DECISION_STAFF, HANDOVER_WAIT  # noqa: E402
from agents.service import Conflict, RequestError, TowerService, demo_backend_factory  # noqa: E402
from agents.sim_director import build_sim_service  # noqa: E402
from agents.supervisor import SHELF_STEP, ReturnRequest, run_return  # noqa: E402
from agents.tools import MockBackend  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402

ENV = {"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}
OTHERS = ["초량역 1번 출구 검정 카드지갑 주웠어요", "중앙역 대합실 흰색 보조배터리 주웠어요",
          "중앙역 2번 출구 흰색 핸드크림 주웠어요", "초량역 개찰구 흰색 보조배터리 주웠어요"]
LIPBALM = "초량역 화장실 앞 립밤 주웠어요"            # 11/9 운영 품목에서 뺌


def until(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class SimFullTest(unittest.TestCase):
    def setUp(self):
        self.svc = build_sim_service(ENV)
        self.d = self.svc.sim
        self.w = self.svc.world

    def found(self, text):
        r = self.d.found(text)
        self.assertTrue(self.d.wait_idle())
        return r["item_id"]

    def slot(self, item_id):
        return self.w.slot_id_of(item_id)

    def test_each_category_goes_to_its_column(self):
        # 시작(예전 5개 묶음, 11/10 018 배치): R1 휴대폰 2칸 · R2 보조배터리 2칸 · R4-1 카드지갑 참 → 빈 칸 = R3-1 · R3-2 · R4-2
        seed = {self.slot(i) for i in self.w.items}
        self.assertEqual(seed, {"R1-1", "R1-2", "R2-1", "R2-2", "R4-1"})
        a = self.found(OTHERS[0])                                      # 지갑 → 지갑 열
        b = self.found(OTHERS[2])                                      # 핸드크림 → 핸드크림 열
        self.assertEqual((self.slot(a), self.slot(b)), ("R4-2", "R3-1"))
        with self.assertRaises(RequestError) as cm:                    # USB: 11/9 품목 4종 고정 → 접수하지 않음
            self.d.found("초량역 개찰구 은색 USB 주웠어요")
        self.assertIn("운영하지 않는 품목", str(cm.exception))
        with self.assertRaises(RequestError) as cm:                    # 립밤: 운영하지 않는 품목 → 접수하지 않음
            self.d.found(LIPBALM)
        self.assertIn("운영하지 않는 품목", str(cm.exception))
        phone = self.found("초량역 3번 출구 빨간 휴대폰 주웠어요")
        self.assertIsNone(self.slot(phone))                            # 휴대폰은 R4-2 가 비어 있어도 넣지 않음
        self.assertEqual((self.w.items[phone]["loc"], self.w.items[phone]["status"]), ("kiosk", "등록기계 보관"))
        self.assertIn(phone, self.w.wait_queue)
        alerts = [m for m in self.svc.reporter.messages if m.get("channel") == "alert" and phone in m["title"]]
        self.assertTrue(alerts and "회수 대기" in alerts[-1]["title"] and "휴대폰 2/2" in alerts[-1]["title"], alerts)
        self.assertNotIn("010", str(alerts))
        st = self.svc.storage_status()
        self.assertEqual({g["key"]: (g["used"], g["total"], g["waiting"]) for g in st["groups"]},
                         {"phone": (2, 2, 1), "지갑": (2, 2, 0), "보조배터리": (2, 2, 0), "핸드크림": (1, 2, 0)})
        self.assertEqual([x["item_id"] for x in st["waiting"]], [phone])
        self.assertEqual(st["message"], "보관 칸이 다 찼어요 · 대기 1건")

    def test_full_wait_then_shelf_move_auto_collects_in_order(self):
        # 보조배터리 열(R3)은 시연 보조배터리 2개로 처음부터 참(11/9 품목 4종)
        w1 = self.found(OTHERS[1])                                     # 보조배터리
        w2 = self.found(OTHERS[3])                                     # 보조배터리 하나 더
        self.assertEqual(self.w.wait_queue, [w1, w2])                   # 먼저 온 순서
        arr = {a["item_id"]: a for a in self.svc.storage_arrivals()}
        self.assertTrue(arr[w1]["slot_wait"] and arr[w1]["wait_no"] == 1 and arr[w2]["wait_no"] == 2)
        self.assertTrue(arr[w1]["recommended"]["shelf"])               # 맞는 빈 칸 없음 → 선반 추천
        st = self.svc.storage_status()
        self.assertIsNotNone(st["suggest"])                            # 가장 오래 보관된 물건부터 선반으로 제안
        oldest = st["suggest"]["item_id"]
        freed = self.slot(oldest)
        out = self.svc.move_to_shelf({"item_id": oldest})
        self.assertEqual(out["slot_id"], "S-1")
        self.assertTrue(until(lambda: self.slot(w1) == freed), (self.w.wait_queue, self.slot(w1)))
        self.assertTrue(self.d.wait_idle())
        self.assertEqual(self.w.items[w1]["status"], "본센터 보관")
        self.assertEqual(self.w.wait_queue, [w2])                       # 뒤 물건은 계속 대기
        self.assertEqual(self.w.items[oldest]["loc"], "shelf")
        self.assertEqual(self.svc.storage_status()["shelf"][0]["item_id"], oldest)
        # 칸 대기 물건을 직원이 바로 선반으로 → 대기 줄에서 빠지고 본센터 보관
        self.svc.move_to_shelf({"item_id": w2})
        self.assertEqual((self.w.items[w2]["loc"], self.w.items[w2]["status"], self.w.wait_queue), ("shelf", "본센터 보관", []))

    def test_handover_done_frees_slot_and_collects_waiting_phone(self):
        phone = self.found("초량역 3번 출구 빨간 휴대폰 주웠어요")
        self.assertIn(phone, self.w.wait_queue)
        r = self.d.lost("화이트 휴대폰 잃어버렸어요 부산역")              # 시연 물건(R1) 반환 → 인계 완료 → 칸이 빔
        if "pending_id" in r:
            r = self.d.answer(r["pending_id"], "모름")
        self.assertTrue(self.d.wait_idle(60))
        self.assertTrue(until(lambda: self.slot(phone) in ("R1-1", "R1-2")), (self.w.wait_queue, self.w.items[phone]))
        self.assertTrue(self.d.wait_idle())
        self.assertEqual(self.w.items[phone]["status"], "본센터 보관")

    def test_shelf_item_is_candidate_and_returned_without_robot(self):
        a = self.found(OTHERS[0])                                      # 검정 카드지갑
        self.svc.move_to_shelf({"item_id": a})
        cands = self.d.candidates({"category": "지갑", "color": "검정"}, None)
        self.assertIn(a, [c["item_id"] for c in cands])                # 선반 물건도 분실 신고 후보
        self.w.arm["phase"] = "대기"
        before = dict(self.w.arm)
        r = self.d.lost("검정 카드지갑 잃어버렸어요 초량역에서요")
        self.assertTrue(self.d.wait_idle(60))
        self.assertEqual(r["item_id"], a)
        st = self.svc.board.story(r["story_id"])
        self.assertTrue(st["result"]["ok"], st["result"])
        stages = {s["key"]: s for s in st["stages"]}
        self.assertEqual({k: stages[k]["state"] for k in ("topview", "match", "approach", "grasp")},
                         dict.fromkeys(("topview", "match", "approach", "grasp"), "skip"))
        self.assertIn("직원이 가져다 드려요", stages["visit"]["detail"] + stages["handover"]["detail"] + stages["deliver"]["detail"]
                      + " ".join(e.get("body") or "" for e in self.svc.board.since(0)))
        self.assertEqual((self.w.items[a]["status"], self.w.items[a]["loc"]), ("인계 완료", "handed"))
        self.assertEqual((self.w.arm["x"], self.w.arm["y"], self.w.arm["holding"]), (before["x"], before["y"], None))
        case = next(c for c in self.svc.recent(5) if c["item_id"] == a)
        self.assertEqual(case["decision"], DECISION_RETURNED)
        self.assertIn(SHELF_STEP, [s["step"] for s in self.svc.get_case(case["case_id"])["steps"]])

    def test_phone_never_recommended_outside_r1(self):
        from agents.storage import recommend_slot
        lay = self.svc.storage.layout()
        self.assertIsNone(recommend_slot(lay, "모형폰"))               # R1 2칸이 참 → 다른 행 추천 안 함
        self.assertEqual(recommend_slot(lay, "지갑")["slot_id"], "R4-2")
        self.assertIsNone(recommend_slot(lay, "보조배터리"))           # R2 2칸이 참 → 다른 열에 넣지 않음
        self.assertEqual(recommend_slot(lay, "핸드크림")["slot_id"], "R3-1")
        self.assertIsNone(recommend_slot(lay, "USB"))                  # 11/9 USB 는 운영 품목이 아님 → 받는 열 없음
        self.assertIsNone(recommend_slot(lay, "립밤"))                 # 운영하지 않는 품목은 받는 열이 없음


class ShelfFlowTest(unittest.TestCase):
    """반환 흐름(supervisor): 선반 물건은 로봇 단계 없이 인계 대기 — 앞 관문은 그대로"""

    def be(self):
        return MockBackend(bin_items=[], db={"A-1": {"status": "본센터 보관", "features": {"category": "지갑", "color": "검정"}}})

    def test_skips_robot_and_waits_for_staff(self):
        be = self.be()
        out = run_return(ReturnRequest("T", "A-1", staff_shelf=True), be, Reporter())
        self.assertEqual(out.decision, DECISION_RETURNED)
        self.assertIn(SHELF_STEP, out.steps)
        self.assertEqual(be.db["A-1"]["status"], HANDOVER_WAIT)
        self.assertFalse([c for c in be.calls if str(c[0] if isinstance(c, tuple) else c).startswith(("robot", "vision"))], be.calls)

    def test_gates_still_apply(self):
        out = run_return(ReturnRequest("T", "A-1", staff_shelf=True, visitor_id_match=False), self.be(), Reporter())
        self.assertEqual(out.decision, DECISION_REJECTED)
        out = run_return(ReturnRequest("T", "A-1", staff_shelf=True, staff_confirmed=False), self.be(), Reporter())
        self.assertEqual(out.decision, DECISION_STAFF)
        out = run_return(ReturnRequest("T", "A-1", staff_shelf=True, quiz_passed=False), self.be(), Reporter())
        self.assertEqual(out.decision, DECISION_REJECTED)


class ServiceShelfTest(unittest.TestCase):
    """실제 DB 모드와 같은 서비스 규칙(메모리 보관함·시연 부품)"""

    def setUp(self):
        self.svc = TowerService(demo_backend_factory(), Reporter())

    def test_request_cannot_claim_shelf(self):
        from agents.service import GATE_FIELDS, parse_request
        self.assertNotIn("staff_shelf", GATE_FIELDS)
        with self.assertRaises(RequestError):
            parse_request({"case_id": "C1", "item_id": "A-W01", "staff_shelf": True, **{g: True for g in GATE_FIELDS}})

    def test_shelf_return_skips_robot_even_when_stopped(self):
        from agents.service import GATE_FIELDS
        self.svc.storage.assign("A-W01", "R4-1", override_category=True)
        self.svc.move_to_shelf({"item_id": "A-W01"})
        self.svc.stop_robot()
        out = self.svc.start_return({"case_id": "SH1", "item_id": "A-W01", **{g: True for g in GATE_FIELDS}})
        self.assertEqual(out["decision"], DECISION_RETURNED)
        self.assertIn("선반", out["reason"])
        q = [x for x in self.svc.handover_queue() if x["case_id"] == "SH1"]
        self.assertTrue(q and q[0]["staff_shelf"] and q[0]["slot"] == "S-1")
        self.assertEqual(self.svc.verify_handover("SH1", {"item_match": True, "id_match": True, "feature_match": True})["result"],
                         "인계 완료")
        with self.assertRaises(Conflict):                               # 로봇 물건은 정지 중에 시작 안 됨(그대로)
            self.svc.storage.assign("A-W02", "R4-2", override_category=True)
            self.svc.start_return({"case_id": "SH2", "item_id": "A-W02", **{g: True for g in GATE_FIELDS}})

    def test_arrivals_recommend_shelf_when_no_slot(self):
        for i, sid in enumerate(["R2-1", "R2-2", "R3-1", "R3-2", "R4-1", "R4-2"], start=1):
            self.svc.storage.assign(f"A-W0{i}", sid, override_category=True)
        st = self.svc.create_item({"machine_id": "KIOSK-A", "place_text": "대합실"})["item_id"]
        self.svc.set_item_features(st, {"qwen": {"category": "wallet", "colors": ["black"]}, "confidence": 0.9})
        arr = {a["item_id"]: a for a in self.svc.storage_arrivals()}
        self.assertTrue(arr[st]["slot_wait"])
        self.assertTrue(arr[st]["recommended"]["shelf"])
        alerts = [m for m in self.svc.reporter.messages if m.get("channel") == "alert" and st in m["title"]]
        self.assertTrue(alerts and "지갑 2/2" in alerts[0]["title"], self.svc.reporter.messages[-3:])
        status = self.svc.storage_status()
        self.assertEqual(status["message"], "보관 칸이 다 찼어요 · 대기 1건")
        self.assertIsNotNone(status["suggest"])
        with self.assertRaises(RequestError):
            self.svc.move_to_shelf({"item_id": st, "x": 1})
        out = self.svc.move_to_shelf({"item_id": st})                   # 칸 대기 물건을 직원이 가져와 선반에
        self.assertEqual((out["slot_id"], out["status"]), ("S-1", "본센터 보관"))
        self.assertEqual(self.svc.storage_status()["waiting"], [])


if __name__ == "__main__":
    unittest.main()
