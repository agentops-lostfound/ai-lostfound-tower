"""전체 가상 시연(LF-29, 11/4) — 가상 부품·연출기·기록판·분실물 봇 핵심 시험. 시간 배수 0 으로 기다리지 않는다."""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.backends import check_part  # noqa: E402
from agents.contracts import CLAIM_ID_RE, ITEM_ID_RE, MACHINE_LETTERS  # noqa: E402
from agents.live import LiveBoard, LiveReporter  # noqa: E402
from agents.service import RequestError  # noqa: E402
from agents.sim_director import build_sim_service  # noqa: E402
from agents.sim_world import SimRobot, SimTopview, SimWorld, parse_place, query_features, sim_qwen, split_tags  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402
from tools import lostfound_bot as bot  # noqa: E402

ENV = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}
FOUND = "서면역 5번 출구 앞에서 검정 카드지갑 주웠어요"


def story_of(svc, sid):
    return svc.board.story(sid)


class SimPartsTest(unittest.TestCase):
    def test_parts_keep_contracts(self):
        w = SimWorld(speed=0)
        self.assertEqual(check_part(w, "db"), [])
        self.assertEqual(check_part(SimTopview(w), "vision"), [])
        self.assertEqual(check_part(SimRobot(w), "robot"), [])

    def test_seomyeon_letter_does_not_look_like_claim_id(self):
        self.assertEqual(MACHINE_LETTERS["KIOSK-C"], "S")
        w = SimWorld(speed=0, seed=False)
        row = w.create({"machine_id": "KIOSK-C", "place_text": "서면역", "finder": None})
        self.assertTrue(ITEM_ID_RE.match(row["item_id"]))
        self.assertFalse(CLAIM_ID_RE.match(row["item_id"]))

    def test_parse_message(self):
        self.assertEqual(parse_place(FOUND), ("KIOSK-C", "서면역 5번 출구 앞"))
        self.assertEqual(parse_place("어제 해운대역 화장실에서 립밤 주웠어요"), ("KIOSK-A", "해운대역 화장실"))
        self.assertEqual(parse_place("지갑 주웠어요")[0], None)
        q = sim_qwen("검정 보조배터리 VOVA 글자")
        self.assertEqual((q["category"], q["colors"], q["logos_or_text"]), ("power_bank", ["black"], ["VOVA"]))
        f = query_features("검정 카드지갑 잃어버렸어요")
        self.assertEqual(f, {"category": "지갑", "color": "검정"})      # 말하지 않은 칸은 비교하지 않음
        self.assertEqual(split_tags("지갑 #집기실패 #보정실패"), ("지갑", {"grasp_fail", "calib_fail"}))

    def test_topview_goes_through_real_adapter_with_calibration_gate(self):
        w = SimWorld(speed=0)
        dets = SimTopview(w).vision_topview()
        self.assertEqual(len(dets), 8)
        self.assertTrue(all("center_mm" in d for d in dets))
        w.inject(calib_fail=True)
        dets = SimTopview(w).vision_topview()
        self.assertTrue(dets and all("center_mm" not in d for d in dets))   # 보정 없음 → mm 없음 → 로봇 안 움직임

    def test_so101_six_joints_follow_motion(self):
        """SO-101: 모터 6개(축 5 + 집게). 집을 때 집게가 닫히고 높이가 내려가며, 내려놓은 뒤 원점 복귀는 뒤에서"""
        from agents.sim_world import SO101_JOINTS, SLOTS_MM
        self.assertEqual([n for n, _ in SO101_JOINTS], ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex",
                                                        "wrist_roll", "gripper"])
        w = SimWorld(speed=0)
        r = SimRobot(w)
        self.assertEqual(set(w.arm["joints"]), {n for n, _ in SO101_JOINTS})
        self.assertTrue(r.robot_approach(list(SLOTS_MM[0]), [0, 0])["ok"])
        self.assertTrue(r.robot_grasp()["ok"])
        self.assertLess(w.arm["joints"]["gripper"], 20)            # 집게 닫힘
        self.assertTrue(r.robot_deliver()["ok"])
        if w.homing:
            w.homing.join(5)
        self.assertEqual((w.arm["x"], w.arm["y"], w.arm["phase"]), (240.0, 345.0, "대기"))
        self.assertEqual(sum(1 for i in w.items.values() if i["loc"] == "basket"), 1)
        snap = w.snapshot()
        self.assertEqual(len(snap["robot"]["joints"]), 6)

    def test_robot_stop_halts_motion_midway(self):
        w = SimWorld(speed=1)
        r = SimRobot(w)
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", r.robot_approach([60.0, 60.0], [160, 150])))
        t.start()
        time.sleep(0.4)
        r.robot_stop()
        t.join(5)
        self.assertFalse(out["r"]["ok"])
        self.assertTrue(w.arm["stopped"])
        self.assertFalse(r.robot_grasp()["ok"])          # 원점 복귀 전에는 다음 동작도 거부
        w.speed = 0
        self.assertTrue(r.robot_home()["ok"])
        self.assertFalse(w.arm["stopped"])


class DirectorTest(unittest.TestCase):
    def setUp(self):
        self.svc = build_sim_service(ENV)
        self.d = self.svc.sim

    def found(self, text=FOUND):
        r = self.d.found(text)
        self.assertTrue(self.d.wait_idle())
        return r

    def lost(self, text):
        r = self.d.lost(text)
        self.assertTrue(self.d.wait_idle())
        return r

    def test_full_story_found_to_handover(self):
        f = self.found()
        self.assertTrue(f["item_id"].startswith("S-"))
        self.assertEqual(story_of(self.svc, f["story_id"])["result"]["ok"], True)
        r = self.lost("검정 카드지갑 잃어버렸어요 서면역에서요")
        self.assertEqual(r["item_id"], f["item_id"])
        st = story_of(self.svc, r["story_id"])
        self.assertTrue(st["result"]["ok"], st["result"])
        self.assertTrue(all(s["state"] == "done" for s in st["stages"]), st["stages"])
        self.assertEqual(self.svc.world.items[f["item_id"]]["status"], "인계 완료")
        self.assertEqual(self.svc.world.items[f["item_id"]]["loc"], "handed")
        titles = [m["title"] for m in self.svc.reporter.messages]
        self.assertTrue(any("등록기계 접수" in t for t in titles) and any("인계 완료" in t for t in titles))

    def test_quiz_question_then_wrong_answer_is_rejected(self):
        r = self.d.lost("은색 USB 잃어버렸어요")
        self.assertIn("pending_id", r)
        out = self.d.answer(r["pending_id"], "Kingston")
        self.assertFalse(out["quiz_passed"])
        self.assertTrue(self.d.wait_idle())
        st = story_of(self.svc, out["story_id"])
        self.assertFalse(st["result"]["ok"])
        self.assertIn("rejected", st["result"]["text"])
        self.assertEqual(self.svc.world.arm["holding"], None)
        self.assertEqual(sum(1 for i in self.svc.world.items.values() if i["loc"] == "bin"), 8)   # 로봇 안 움직임

    def test_calibration_fail_tag_sends_to_staff(self):
        self.found()
        r = self.lost("검정 카드지갑 잃어버렸어요 서면역 #보정실패")
        st = story_of(self.svc, r["story_id"])
        self.assertIn("staff_check", st["result"]["text"])
        self.assertIn("작업대 좌표 없음", st["result"]["text"])
        self.assertEqual(self.svc.world.items[r["item_id"]]["loc"], "bin")

    def test_grasp_fail_tag_retries_and_returns(self):
        self.found()
        r = self.lost("검정 카드지갑 잃어버렸어요 서면역 #집기실패")
        st = story_of(self.svc, r["story_id"])
        self.assertTrue(st["result"]["ok"])
        self.assertTrue(any("집기 실패" in m["title"] for m in self.svc.reporter.messages))

    def test_id_mismatch_tag_rejects(self):
        self.found()
        r = self.lost("검정 카드지갑 잃어버렸어요 서면역 #신분증불일치")
        st = story_of(self.svc, r["story_id"])
        self.assertFalse(st["result"]["ok"])
        self.assertEqual(self.svc.world.items[r["item_id"]]["status"], "반환 보류")

    def test_manual_handover_waits_for_staff(self):
        self.found()
        r = self.lost("검정 카드지갑 잃어버렸어요 서면역 #수동인계")
        self.assertEqual(self.svc.world.items[r["item_id"]]["status"], "인계 대기")
        self.assertEqual(self.svc.world.items[r["item_id"]]["loc"], "basket")
        case = story_of(self.svc, r["story_id"])["ids"]["case_id"]
        self.svc.handover(case, {"staff_confirmed": True})
        self.assertEqual(self.svc.world.items[r["item_id"]]["loc"], "handed")

    def test_purchased_items_scenes(self):
        """실제 구매 목록 기준(11/4): 핑크샌드 지갑은 분홍으로 구별, 같은 제품 USB 2개는 직원 확인"""
        from agents.sim_world import SEED_ITEMS
        self.assertEqual(len(SEED_ITEMS), 8)
        r = self.lost("분홍 카드지갑 잃어버렸어요")
        self.assertTrue(story_of(self.svc, r["story_id"])["result"]["ok"])
        self.assertEqual(self.svc.world.items[r["item_id"]]["features"]["color"], "분홍")
        p = self.d.lost("은색 USB 잃어버렸어요")
        out = self.d.answer(p["pending_id"], "SanDisk")
        self.assertTrue(out.get("staff"))                               # 똑같은 USB 2개 → 고르지 않고 직원 확인
        self.assertEqual(len(out["candidates"]), 2)
        self.assertTrue(self.d.wait_idle())
        res = story_of(self.svc, out["story_id"])["result"]
        self.assertFalse(res["ok"])
        self.assertIn("staff_check", res["text"])
        self.assertEqual(sum(1 for i in self.svc.world.items.values() if i["category"] == "USB" and i["loc"] == "bin"), 2)

    def test_lookalike_ignores_other_categories(self):
        """11/4 무작위 시험 발견: 흰색 목업폰을 찾을 때 흰색 보조배터리·핸드크림을 '닮은 물건'으로 세면 안 됨"""
        r = self.lost("흰색 모형폰 잃어버렸어요")
        st = story_of(self.svc, r["story_id"])
        self.assertTrue(st["result"]["ok"], st["result"])
        self.assertEqual(self.svc.world.items[r["item_id"]]["category"], "모형폰")

    def test_place_and_color_questions_are_asked(self):
        """11/4: 글자 없는 물건이면 역(등록기계 물건)·색을 먼저 묻는다(예전에는 묻지 않고 오답 처리)"""
        self.found()
        p = self.d.lost("카드지갑 잃어버렸어요")
        self.assertIn("색", p["question"])                     # 지갑 후보가 여럿 → 색부터
        p2 = self.d.answer(p["pending_id"], "검정이요")
        self.assertIn("어느 역", p2["question"])               # 검정 지갑은 서면역 등록기계 물건 → 역 확인
        out = self.d.answer(p2["pending_id"], "서면역이요")
        self.assertTrue(out["quiz_passed"])
        self.assertTrue(self.d.wait_idle())
        self.assertTrue(story_of(self.svc, out["story_id"])["result"]["ok"])

    def test_pii_rejected_in_place_and_description(self):
        with self.assertRaises(RequestError):
            self.d.found("서면역 010-1234-5678 에 떨어져 있었어요 검정 지갑")
        p = self.d.lost("은색 USB 잃어버렸어요")
        with self.assertRaises(RequestError):
            self.d.answer(p["pending_id"], "010-9999-8888")

    def test_item_numbers_continue_after_reset(self):
        a = self.found()["item_id"]
        self.d.reset()
        b = self.found()["item_id"]
        self.assertNotEqual(a, b)

    def test_bad_messages(self):
        with self.assertRaises(RequestError):
            self.d.found("지갑 주웠어요")                       # 역 없음
        with self.assertRaises(RequestError):
            self.d.found("서면역에서 뭔가 주웠어요")              # 품목 없음
        with self.assertRaises(RequestError):
            self.d.lost("립밤 잃어버렸어요")                    # 후보 없음
        self.assertEqual(self.svc.board.stories, {})            # 실패한 신고는 이야기를 만들지 않음

    def test_reset_restores_seed_and_keeps_claim_numbers(self):
        self.found()
        r1 = self.lost("검정 카드지갑 잃어버렸어요 서면역")
        self.d.reset()
        self.assertEqual(len(self.svc.world.items), 8)
        self.found()
        r2 = self.lost("검정 카드지갑 잃어버렸어요 서면역")
        self.assertNotEqual(r1["claim_id"], r2["claim_id"])
        self.assertTrue(story_of(self.svc, r2["story_id"])["result"]["ok"])


class LiveBoardTest(unittest.TestCase):
    def test_reporter_mirrors_and_blocks_pii(self):
        b = LiveBoard()
        rep = LiveReporter(Reporter(), b)
        rep.progress("A-1", "탑뷰 촬영", "물건 3개")
        rep.alert("A-1", "연락처 010-1234-5678")
        self.assertEqual([e["title"] for e in b.since(0)], ["[A-1] 탑뷰 촬영"])
        self.assertEqual(len(rep.blocked), 1)

    def test_alert_marks_first_unfinished_stage(self):
        b = LiveBoard()
        rep = LiveReporter(Reporter(), b)
        sid = b.new_story("lost", "t")
        with b.bind(sid):
            b.stage("claim", "done")
            rep.progress("R", "메인 AI 승인 · 수령 예약")
            rep.alert("R", "방문자 신분증 불일치")
        states = {s["key"]: s["state"] for s in b.story(sid)["stages"]}
        self.assertEqual((states["approve"], states["visit"]), ("done", "fail"))

    def test_alert_keyword_and_finish_clear_active(self):
        b = LiveBoard()
        rep = LiveReporter(Reporter(), b)
        sid = b.new_story("lost", "t")
        with b.bind(sid):
            b.stage("claim", "done")
            b.stage("visit", "active")
            rep.alert("R", "확인 질문 미통과 — 승인하지 않음")
        b.finish(sid, "반환 안 함", False)
        states = {s["key"]: s["state"] for s in b.story(sid)["stages"]}
        self.assertEqual((states["approve"], states["visit"]), ("fail", "todo"))   # 진행 중 표시가 남지 않음


class FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, path, body=None):
        self.calls.append((path, body))
        if path == "/sim/lost":
            return {"pending_id": "p1", "question": "글자?", "candidates": [{"item_id": "H-1", "card": "c", "station": "s"}]}
        if path.endswith("/answer"):
            return {"claim_id": "C-20261104-0001", "item_id": "H-1", "quiz_passed": True, "story_id": "T002"}
        if path == "/sim/found":
            return {"item_id": "S-1", "place_text": "서면역", "machine_id": "KIOSK-C", "features": "f", "story_id": "T001"}
        return {"ok": True}

    def get(self, path):
        return {"story_id": "T001", "kind": "found", "ids": {}, "stages": [], "result": {"ok": True, "text": "끝"}}


class BotCoreTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(bot.classify(FOUND), "found")
        self.assertEqual(bot.classify("검정 지갑 잃어버렸어요"), "lost")
        self.assertEqual(bot.classify("정지"), "stop")
        self.assertEqual(bot.classify("!도움말"), "help")
        self.assertEqual(bot.classify("안녕"), "unknown")

    def test_quiz_answer_goes_to_pending(self):
        c = bot.BotCore(FakeClient())
        reply, story = c.handle("u", "지갑 잃어버렸어요")
        self.assertIn("확인 질문", reply)
        self.assertIsNone(story)
        reply, story = c.handle("u", "VOVA")
        self.assertEqual(story, "T002")
        self.assertEqual(c.client.calls[-1], ("/sim/lost/p1/answer", {"text": "VOVA"}))
        self.assertEqual(c.handle("u", "VOVA")[1], None)        # 답은 한 번만

    def test_new_report_drops_old_question(self):
        """11/4 무작위 시험 발견: 답하지 않은 옛 질문이 남아 다음 말이 옛 질문의 답으로 들어가면 안 됨"""
        c = bot.BotCore(FakeClient())
        c.handle("u", "지갑 잃어버렸어요")
        self.assertIn("u", c.pending)
        c.handle("u", "서면역 앞에서 검정 지갑 주웠어요")          # 새 신고
        self.assertNotIn("u", c.pending)
        reply, _ = c.handle("u", "VOVA")
        self.assertIn("모르겠어요", reply)

    def test_follow_updates_until_result(self):
        c = bot.BotCore(FakeClient())
        seen = []
        st = c.follow("T001", seen.append, sleep=lambda s: None)
        self.assertTrue(st["result"]["ok"])
        self.assertEqual(len(seen), 1)

    def test_tower_down_message(self):
        c = bot.BotCore(bot.TowerClient("http://127.0.0.1:9", timeout=0.5))
        reply, story = c.handle("u", FOUND)
        self.assertIn("관제탑에 연결할 수 없어요", reply)


if __name__ == "__main__":
    unittest.main()
