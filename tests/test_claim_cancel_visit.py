"""11/10 사용자 결정 — 찾기 요청 취소 · 잃어버린 장소 '모름' · 직원 확인으로 진행 · 처음 물건은 중앙역 습득.

1) 처음 보관된 분홍 핸드크림은 중앙역 등록기계에서 주운 물건(A-…-0001, R3-1)
2) 잃어버린 역을 모르면 장소는 묻지도 채점하지도 않고 색으로 확인한다. 역을 틀리게 말하면 그대로 미통과
3) 확인 질문이 맞지 않아 키오스크가 받지 않는 요청은 직원이 [직원 확인 후 진행]으로 넘긴다
4) 방문 전인 찾기 요청·방문 예약은 취소할 수 있다(직원 / 분실인 본인). 물건은 계속 보관되고 다시 신고할 수 있다
"""
import os
import sys
import unittest
from chat_confirmation_helpers import ui_step, ui_ask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agents.service import Conflict, NotFound, RequestError  # noqa: E402

ENV = {"TOWER_SIM_SEED": "cream", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}   # 11/11 기본은 빈 보관함 → 분홍 핸드크림 묶음
OPT = {"visit": "kiosk", "name_masked": "홍*동", "id_no_masked": "******-1******"}
KIOSK = {"machine_id": "CENTER", "id_no_masked": "******-1******"}


def make():
    from agents.sim_director import build_sim_service
    svc = build_sim_service(ENV)
    return svc, svc.sim


def stages(svc, cid):
    st = next(s for s in svc.board.stories.values() if s["ids"].get("claim_id") == cid)
    return {x["key"]: x["state"] for x in st["stages"]}, (st["result"] or {})


class SeedPlaceTest(unittest.TestCase):
    def test_pink_hand_cream_was_found_at_haeundae(self):
        svc, _ = make()
        (row,) = svc.world.items.values()
        self.assertEqual((row["machine_id"], row["place_text"], row["status"]), ("KIOSK-A", "중앙역 승강장", "본센터 보관"))
        self.assertTrue(row["item_id"].startswith("A-") and row["item_id"].endswith("-0001"))
        self.assertEqual(svc.world.slot_id_of(row["item_id"]), "R3-1")

    def test_next_haeundae_item_number_continues(self):
        svc, d = make()
        r = d.found("중앙역에서 흰색 보조배터리 주웠어요")
        self.assertTrue(r["item_id"].endswith("-0002"), r["item_id"])       # 처음 물건이 0001

    def test_full_seed_still_center(self):
        from agents.sim_director import build_sim_service
        svc = build_sim_service({**ENV, "TOWER_SIM_SEED": "full"})
        self.assertEqual({r["machine_id"] for r in svc.world.items.values()}, {"CENTER"})


class UnknownPlaceTest(unittest.TestCase):
    def claim(self, svc, r):
        return svc.claims.get(r["claim_id"])

    def test_right_station_passes_wrong_station_fails(self):
        svc, d = make()
        r = d.lost("중앙역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))
        self.assertTrue(r["quiz_passed"])
        self.assertEqual(self.claim(svc, r)["quiz"], [{"field": "place", "passed": True}])
        svc, d = make()
        r = d.lost("초량역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))
        self.assertFalse(r["quiz_passed"])                                  # 틀리게 말한 것은 모름과 다르다
        self.assertEqual(self.claim(svc, r)["quiz"], [{"field": "place", "passed": False}])

    def test_asked_then_unknown_uses_color(self):
        svc, d = make()
        r = d.lost("분홍 핸드크림 잃어버렸어요", dict(OPT))
        self.assertIn("모름", r["question"])                                # 모른다고 답해도 된다고 알려 줌
        for say in ("모름", "기억 안 나요", "잘 모르겠어요", "몰라요"):
            svc, d = make()
            r = d.answer(d.lost("분홍 핸드크림 잃어버렸어요", dict(OPT))["pending_id"], say)
            self.assertTrue(r.get("quiz_passed"), say)
            c = self.claim(svc, r)
            self.assertEqual((c["quiz"], c.get("lost_station")), ([{"field": "color", "passed": True}], None), say)

    def test_unknown_flag_and_sentence_skip_place_question(self):
        svc, d = make()
        r = d.lost("분홍 핸드크림 잃어버렸어요", {**OPT, "place_unknown": True})       # 웹 '잘 모르겠어요' · 챗봇 '모름'
        self.assertNotIn("pending_id", r)
        self.assertTrue(r["quiz_passed"])
        svc, d = make()
        r = d.lost("분홍 핸드크림 잃어버렸는데 어디서 잃어버렸는지 모르겠어요", dict(OPT))
        self.assertNotIn("pending_id", r)
        self.assertEqual(self.claim(svc, r)["quiz"], [{"field": "color", "passed": True}])

    def test_unknown_place_and_no_color_asks_color(self):
        svc, d = make()
        r = d.lost("핸드크림 잃어버렸어요", {**OPT, "place_unknown": True})
        self.assertEqual(r["question"], "물건 색이 무엇인가요?")            # 장소 대신 색을 묻는다
        ok = d.answer(r["pending_id"], "분홍")
        self.assertTrue(ok["quiz_passed"])
        svc, d = make()
        r = d.lost("핸드크림 잃어버렸어요", {**OPT, "place_unknown": True})
        bad = d.answer(r["pending_id"], "모름")
        self.assertFalse(bad["quiz_passed"])                                # 아무것도 확인하지 못하면 통과시키지 않는다(직원 확인으로)

    def test_chatbot_intake_unknown_station(self):
        from agents.chat_intake import CHOICES, IntakeAgent
        self.assertIn("모름", CHOICES["station_lost"])
        self.assertNotIn("모름", CHOICES["station_found"])                  # 주운 역은 등록기계라 꼭 필요
        svc, d = make()
        a = IntakeAgent(desk=d)
        ident = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-1******"}
        out = None
        for q in ("분홍 핸드크림 잃어버렸어요 접수해 주세요", "모름", "어제", "없어요", ident, "네"):
            out = ui_step(a, "s1", "" if isinstance(q, dict) else q, action=q if isinstance(q, dict) else None)
        self.assertEqual(out["status"], "intake_done", out["answer"])
        self.assertNotIn("모름역", out["answer"])
        cid = out["intake"]["claim_id"]
        c = svc.claims.get(cid)
        self.assertEqual((c["quiz"], c.get("lost_station")), ([{"field": "color", "passed": True}], None))
        story = next(s for s in svc.board.stories.values() if s["ids"].get("claim_id") == cid)
        self.assertNotIn("모름역", story["title"])


class StartupReseedTest(unittest.TestCase):
    """11/10 실물 연결 모드(김건태 원격 티칭)는 화면의 [가상 세계 초기화]를 막는다. 그래도 관제탑이 켜질 때 팀 DB 와 번호를 맞추는
    다시 채우기(startup=True)는 되어야 한다 — 안 되면 처음 물건 번호가 진짜 접수와 겹친 채 남고, 찾기 요청이 진짜 물건에 걸린다"""

    def test_startup_reseed_allowed_but_button_blocked(self):
        svc, d = make()
        svc.taught_robot = True
        with self.assertRaises(Conflict):
            d.reset()
        first = list(svc.world.items)
        d.reset(startup=True)
        (row,) = svc.world.items.values()
        self.assertNotEqual(list(svc.world.items), first)                   # 번호가 이어져 새 번호를 받음
        self.assertEqual((row["machine_id"], svc.world.slot_id_of(row["item_id"])), ("KIOSK-A", "R3-1"))


class LostStationTest(unittest.TestCase):
    """11/10 본센터(부산역) 키오스크에서 주운 물건: 챗봇 분실 접수의 역 선택지가 초량·중앙뿐이라 "부산역"이라고 답할 길이 없었다"""

    def center_item(self):
        from agents.sim_world import LOC_BIN, sim_qwen, to_features
        svc, d = make()
        w = svc.world
        row = w.create({"machine_id": "CENTER", "place_id": None, "place_text": "열차 안", "finder": None, "photo_path": None})
        q = sim_qwen("초록 핸드크림")
        w.set_features(row["item_id"], to_features(q, 0.9), qwen=q)
        w.items[row["item_id"]]["status"] = "본센터 보관"
        w.move(row["item_id"], LOC_BIN)
        return svc, d, row["item_id"]

    def intake(self, station_answer):
        from agents.chat_intake import IntakeAgent
        svc, d, iid = self.center_item()
        a = IntakeAgent(desk=d)
        ident = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-1******"}
        first = out = None
        for x in ("초록색 핸드크림을 잃어버렸는데 분실 접수좀 해줘", station_answer, "어제", "없어요", ident, "네"):
            out = ui_step(a, "s", "" if isinstance(x, dict) else x, action=x if isinstance(x, dict) else None)
            first = first or out
        self.assertEqual(out["status"], "intake_done", out["answer"])
        c = svc.claims.get(out["intake"]["claim_id"])
        self.assertEqual(c["item_id"], iid)
        return first, c

    def test_choices_include_busan_and_unknown(self):
        first, _ = self.intake("부산역")
        self.assertEqual(first["choices"], ["초량", "중앙", "부산역", "모름", "취소"])
        self.assertIn("부산역", first["answer"])

    def test_busan_station_matches_center_item(self):
        _, c = self.intake("부산역")
        self.assertEqual((c["quiz"], c["lost_station"]), ([{"field": "place", "passed": True}, {"field": "color", "passed": True}], "부산"))

    def test_other_named_station_is_wrong_but_unknown_is_not(self):
        _, c = self.intake("중앙")
        self.assertEqual(c["quiz"][0], {"field": "place", "passed": False})          # 주운 곳과 다른 역 → 키오스크 대신 직원 확인
        for say in ("모름", "센텀시티역이요", "열차 안에서요", "기억이 잘 안 나요", "다른 역이요"):
            _, c = self.intake(say)
            self.assertEqual((c["quiz"], c.get("lost_station")), ([{"field": "color", "passed": True}], None), say)

    def test_reading_rules(self):
        from agents.chat_intake import extract
        from agents.sim_world import lost_station
        self.assertEqual(lost_station("부산역에서 잃어버렸어요"), "부산")
        self.assertIsNone(lost_station("부산 지하철에서 잃어버렸어요"))               # 도시 이름
        self.assertIsNone(lost_station("본센터 운영시간 알려줘"))                     # 접수 중에 끼어든 안내 질문
        self.assertEqual(lost_station("부산역 가다가 중앙에서 잃어버림"), "중앙")
        self.assertEqual(extract("어제", "lost", "station"), {"when": "어제"})        # 다른 칸 답은 그 칸으로
        self.assertEqual(extract("네", "lost", "station"), {})
        self.assertEqual(extract("부산역이요", "found", "station"), {})               # 주운 역은 등록기계 역만(본센터 습득은 본센터 키오스크)

    def test_discord_style_sentence(self):
        svc, d, iid = self.center_item()
        r = d.lost("부산역에서 초록 핸드크림 잃어버렸어요", dict(OPT))
        self.assertTrue(r["quiz_passed"])
        self.assertEqual(r["item_id"], iid)


class StaffVisitTest(unittest.TestCase):
    def test_failed_quiz_blocked_at_kiosk_then_staff_goes_on(self):
        svc, d = make()
        r = d.lost("초량역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))
        cid = r["claim_id"]
        self.assertTrue(d.wait_idle())
        (oc,) = d.open_claims()
        self.assertEqual((oc["claim_id"], oc["visit_wait"], oc["quiz_passed"]), (cid, True, False))
        self.assertEqual(set(oc), {"claim_id", "story_id", "item_id", "visit_wait", "quiz_passed"})   # 개인정보 없음
        with self.assertRaises(Conflict):
            d.kiosk_return({**KIOSK, "claim_id": cid})                      # 키오스크는 받지 않는다(역무실로)
        out = d.staff_visit(cid)
        self.assertEqual(out["decision"], "returned", out)
        st, res = stages(svc, cid)
        self.assertEqual((st["claim"], st["approve"], st["visit"], st["deliver"]), ("done", "done", "done", "done"))
        self.assertTrue(res["ok"])
        self.assertEqual(svc.claims.get(cid)["quiz"], [{"field": "place", "passed": False}])   # 저장된 확인 질문 결과는 고치지 않음
        self.assertEqual(svc.world.items[r["item_id"]]["status"], "인계 대기")                  # 건네기 전 직원 교차 검증이 남는다
        self.assertEqual(d.open_claims(), [])
        with self.assertRaises(Conflict):
            d.staff_visit(cid)                                              # 두 번 진행하지 않는다

    def test_passed_claim_can_also_go_by_staff(self):
        svc, d = make()
        cid = d.lost("중앙역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))["claim_id"]
        self.assertTrue(d.wait_idle())
        self.assertEqual(d.staff_visit(cid)["decision"], "returned")        # 키오스크를 못 쓰는 분실인

    def test_wrong_ids(self):
        svc, d = make()
        with self.assertRaises(NotFound):
            d.staff_visit("C-20261110-0999")
        with self.assertRaises(RequestError):
            d.staff_visit("x")

    def test_override_needs_all_staff_checks_and_does_not_cover_identity(self):
        svc, d = make()
        cid = d.lost("초량역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))["claim_id"]
        self.assertTrue(d.wait_idle())
        base = {"claim_id": cid, "visitor_id_match": True, "inner_feature_ok": True, "staff_confirmed": True}
        with self.assertRaises(RequestError):
            svc.start_return({**base, "inner_feature_ok": False, "staff_quiz_override": True})   # 직원 확인을 다 하지 않음
        with self.assertRaises(RequestError):
            svc.start_return({**base, "staff_quiz_override": "yes"})
        out = svc.start_return(dict(base))                                  # 대신 통과 표시가 없으면 예전 그대로 거절
        self.assertEqual((out["decision"], out["reason"]), ("rejected", "확인 질문 미통과 — 승인하지 않음"))


class CancelTest(unittest.TestCase):
    def test_owner_cancel_needs_same_masked_id(self):
        svc, d = make()
        r = d.lost("중앙역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))
        cid, iid = r["claim_id"], r["item_id"]
        self.assertTrue(d.wait_idle())
        with self.assertRaises(RequestError):
            d.cancel_claim(cid, id_no_masked="******-2******")
        with self.assertRaises(RequestError):
            d.cancel_claim(cid)                                             # 신분 번호 없이 분실인 취소는 안 됨
        self.assertEqual(svc.claims.get(cid)["status"], "booked")
        out = d.cancel_claim(cid, id_no_masked="******-1******")
        self.assertEqual(out, {"ok": True, "claim_id": cid, "item_id": iid, "status": "cancelled"})
        st, res = stages(svc, cid)
        self.assertEqual(st["visit"], "fail")
        self.assertFalse(res["ok"])
        self.assertIn("취소", res["text"])
        self.assertEqual((svc.world.items[iid]["status"], svc.world.slot_id_of(iid)), ("본센터 보관", "R3-1"))   # 물건은 그대로
        self.assertEqual(d.open_claims(), [])
        for fn in (lambda: d.kiosk_return({**KIOSK, "claim_id": cid}), lambda: d.staff_visit(cid),
                   lambda: d.cancel_claim(cid, by_staff=True)):
            with self.assertRaises(Conflict):
                fn()
        again = d.lost("중앙역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))  # 취소한 뒤 다시 신고할 수 있다
        self.assertNotEqual(again["claim_id"], cid)
        self.assertEqual(again["item_id"], iid)

    def test_owner_cancel_locks_after_many_wrong_ids(self):
        svc, d = make()
        cid = d.lost("중앙역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))["claim_id"]
        d.wait_idle()
        seen = []
        for _ in range(8):
            try:
                d.cancel_claim(cid, id_no_masked="******-2******")
            except RequestError:
                seen.append("wrong")
            except Conflict as e:
                seen.append(e.kind)
        self.assertIn("locked", seen)
        self.assertEqual(svc.claims.get(cid)["status"], "booked")
        self.assertEqual(d.cancel_claim(cid, by_staff=True)["status"], "cancelled")     # 직원은 풀 수 있다

    def test_cannot_cancel_after_return_started(self):
        svc, d = make()
        cid = d.lost("중앙역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))["claim_id"]
        d.wait_idle()
        d.kiosk_return({**KIOSK, "claim_id": cid})
        with self.assertRaises(Conflict):
            d.cancel_claim(cid, by_staff=True)

    def test_bad_numbers(self):
        svc, d = make()
        with self.assertRaises(NotFound):
            d.cancel_claim("C-20261110-0999", by_staff=True)
        with self.assertRaises(RequestError):
            d.cancel_claim("x", by_staff=True)

    def test_memory_store_cancel_only_booked(self):
        from agents.claims import MemoryClaimStore
        s = MemoryClaimStore()
        row = s.create({"item_id": "A-20261110-0001", "quiz": [{"field": "color", "passed": True}], "name_masked": "홍*동",
                        "id_no_masked": "9*", "id_verified": True, "description": {}, "visit_date": "2026-11-10"})
        cid = row["claim_id"]
        self.assertEqual(s.active_for_item("A-20261110-0001"), cid)
        self.assertTrue(s.cancel(cid))
        self.assertFalse(s.cancel(cid))
        self.assertFalse(s.cancel("C-20261110-0999"))
        self.assertIsNone(s.active_for_item("A-20261110-0001"))
        self.assertEqual(s.get(cid)["status"], "cancelled")                 # 기록은 남는다


class ApiTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
        except Exception as e:                                              # pragma: no cover
            self.skipTest(f"fastapi 없음: {e}")
        from agents.api import build_app
        self.svc, self.d = make()
        self.c = TestClient(build_app(self.svc))

    def lost(self, text="중앙역에서 분홍 핸드크림 잃어버렸어요", **more):
        r = self.c.post("/sim/lost", json={"text": text, "visit": "kiosk", "name_masked": "홍*동", "id_no_masked": "******-1******", **more})
        self.assertEqual(r.status_code, 200, r.text)
        self.d.wait_idle()
        return r.json()

    def test_state_lists_open_claims_and_buttons_work(self):
        cid = self.lost("초량역에서 분홍 핸드크림 잃어버렸어요")["claim_id"]
        st = self.c.get("/api/admin/live/state").json()
        self.assertEqual([(o["claim_id"], o["visit_wait"], o["quiz_passed"]) for o in st["claims_open"]], [(cid, True, False)])
        r = self.c.post(f"/api/admin/claims/{cid}/visit")
        self.assertEqual((r.status_code, r.json()["decision"]), (200, "returned"), r.text)
        self.assertEqual(self.c.get("/api/admin/live/state").json()["claims_open"], [])
        self.assertEqual(self.c.post(f"/api/admin/claims/{cid}/visit").status_code, 409)
        self.assertEqual(self.c.post(f"/api/admin/claims/{cid}/cancel").status_code, 409)

    def test_cancel_routes(self):
        cid = self.lost()["claim_id"]
        self.assertEqual(self.c.post(f"/api/lost/claims/{cid}/cancel", json={}).status_code, 422)
        self.assertEqual(self.c.post(f"/api/lost/claims/{cid}/cancel", json={"id_no_masked": "******-2******"}).status_code, 422)
        self.assertEqual(self.c.post(f"/api/lost/claims/{cid}/cancel", json={"id_no_masked": "******-1******", "x": 1}).status_code, 422)
        r = self.c.post(f"/api/lost/claims/{cid}/cancel", json={"id_no_masked": "******-1******"})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "cancelled"), r.text)
        self.assertEqual(self.c.post(f"/api/admin/claims/{cid}/cancel").status_code, 409)
        self.assertEqual(self.c.post("/api/admin/claims/C-20261110-0999/cancel").status_code, 404)
        self.assertEqual(self.c.post("/api/admin/claims/nope/cancel").status_code, 422)
        cid2 = self.lost()["claim_id"]
        self.assertEqual(self.c.post(f"/api/admin/claims/{cid2}/cancel").json()["status"], "cancelled")

    def test_place_unknown_from_web(self):
        res = self.lost("분홍 핸드크림 잃어버렸어요", place_unknown=True)
        self.assertNotIn("pending_id", res)
        self.assertTrue(res["quiz_passed"])


if __name__ == "__main__":
    unittest.main()
