"""11/9 에이전트 대화(agents/agent_talk.py) — 메인 AI 아래 요청·답·확인·채점·도움.
11/11: 채점 에이전트는 일부러 덜 채운 첫 답을 연출하지 않고, 다른 기록(정답지·역 표·탑뷰)과 실제로 어긋날 때만 도움 + 직원 경보"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.agent_talk import AgentTalk, grade, build_talk, PASS  # noqa: E402
from agents.live import LiveBoard, LiveReporter  # noqa: E402
from agents.sim_director import build_sim_service  # noqa: E402
from discord_ops.reporter import CHANNELS, NO_FALLBACK, Reporter  # noqa: E402

ENV = {"TOWER_SIM_SEED": "cream", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}
FOUND = "초량역 5번 출구 앞에서 검정 립밤 주웠어요"


def agent_events(svc):
    return [e for e in svc.board.since(0, limit=999) if e["channel"] == "agent"]


class GradeTest(unittest.TestCase):
    def test_score_parts(self):
        need = {"a": "가", "b": "나"}
        self.assertEqual(grade(need, {"a": 1, "b": 2})["score"], 100)
        g = grade(need, {"a": 1})
        self.assertEqual((g["score"], g["missing"]), (65, ["나"]))
        self.assertLess(g["score"], PASS)
        self.assertEqual(grade(need, {"a": 1, "b": 2}, {"a": False})["wrong"], ["가"])
        self.assertEqual(grade(need, {"a": "010-1234-5678", "b": 2})["score"], 0)       # 개인정보 모양이면 0점
        self.assertEqual(grade(need, {"a": "확인 불가", "b": 2})["missing"], ["가"])      # 모르는 값은 빈 값


class TalkTest(unittest.TestCase):
    def setUp(self):
        self.board = LiveBoard()
        self.rep = LiveReporter(Reporter(), self.board)
        self.talk = AgentTalk(self.rep)

    def test_pii_is_hidden_on_screen_and_discord(self):
        self.talk.say("K", "키오스크 AI", "메인 AI", "request", "습득자 010-1234-5678")
        ev = [e for e in self.board.since(0) if e["channel"] == "agent"][0]
        self.assertNotIn("010", ev["body"])
        self.talk.flush("K", "시험")
        self.assertNotIn("010", str(self.rep.inner.messages))

    def test_flush_sends_once_to_agent_channel_and_fits_discord(self):
        for i in range(40):
            self.talk.say("K", "메인 AI", "DB 에이전트", "request", "가" * 200)
        self.talk.flush("K", "시험")
        sent = [m for m in self.rep.inner.messages if m["channel"] == "agent"]
        self.assertEqual(len(sent), 1)
        self.assertLessEqual(len(sent[0]["body"]), 2000)
        self.assertIn("/live", sent[0]["body"])
        self.talk.flush("K", "시험")                           # 두 번 보내지 않음
        self.assertEqual(len([m for m in self.rep.inner.messages if m["channel"] == "agent"]), 1)
        self.assertFalse(any(e["channel"] == "agent" and "시험" in e["title"] for e in self.board.since(0, limit=999)))  # 화면엔 묶음 안 쌓음

    def test_robot_check_stops_when_position_differs(self):
        area = {"slot_id": "R2-1", "bounds_mm": [100, 100, 200, 200]}
        self.assertEqual(self.talk.robot_check("C1", "S-1", [150, 150], area), "")
        why = self.talk.robot_check("C2", "S-1", [300, 150], area)
        self.assertIn("탑뷰 위치가 다름", why)
        self.assertEqual(self.talk.robot_check("C3", "S-1", [300, 150], None), "")        # 칸 기록 없음 → 원래 기준
        self.assertEqual(self.talk.robot_check("C4", "S-1", [300, 150], {"slot_id": "R2-1", "bounds_mm": None}), "")

    def kinds(self, after=0):
        return [e["agent"]["kind"] for e in self.board.since(after, limit=999) if e["channel"] == "agent"]

    def alerts(self):
        return [m for m in self.rep.inner.messages if m["channel"] == "alert"]

    def test_no_staged_help_when_answer_is_right(self):
        # 예전: 첫 답을 일부러 칸 번호만 → 도움 → 배운 점. 이제 처음부터 칸 범위까지 답하고, 맞으면 도움 없음
        self.talk.robot_check("C1", "S-1", [150, 150], {"slot_id": "R2-1", "bounds_mm": [100, 100, 200, 200]})
        k = self.kinds()
        self.assertIn("score", k)
        self.assertFalse({"coach", "reflect", "retry", "learn"} & set(k))
        self.assertEqual(self.alerts(), [])

    def test_position_mismatch_gets_help_but_alert_only_once_from_flow(self):
        self.talk.robot_check("C2", "S-1", [300, 150], {"slot_id": "R2-1", "bounds_mm": [100, 100, 200, 200]})
        self.assertIn("coach", self.kinds())
        self.assertEqual(self.alerts(), [])                       # 반환 흐름이 직원 확인 경보를 보내므로 여기선 안 보냄

    def found(self, cat="handcream", color="분홍", machine="KIOSK-A", place="중앙역 승강장"):
        item = {"item_id": "A-20261111-0005", "machine_id": machine, "status": "등록기계 보관",
                "features": {"category": cat, "color": color}}
        return self.talk.found_registered("A-20261111-0005", item, place)

    def test_found_ok(self):
        from agents.contracts import ACTIVE_CATEGORIES
        r = self.found(cat=ACTIVE_CATEGORIES[2])
        self.assertFalse(r["grade"]["flag"], r)
        self.assertNotIn("coach", self.kinds())

    def test_found_catches_unknown_category_retired_category_and_wrong_station(self):
        from agents.contracts import ACTIVE_CATEGORIES
        for kw, why in ((dict(cat="확인 불가"), "품목"), (dict(cat="지갑"), "품목"),
                        (dict(cat=ACTIVE_CATEGORIES[0], place="초량역 3번 출구"), "역"), (dict(cat=ACTIVE_CATEGORIES[0], color=None), "색")):
            last = self.board.last_seq
            r = self.found(**kw)
            self.assertTrue(r["grade"]["flag"], kw)
            self.assertIn(why, r["grade"]["missing"] + r["grade"]["wrong"], kw)
            self.assertIn("coach", self.kinds(last))
        self.assertEqual(len(self.alerts()), 4)                   # 어긋날 때마다 직원 확인 경보

    def lay(self, r3=(None, None)):
        def sl(sid, who):
            return {"slot_id": sid, "item": {"item_id": who} if who else None}
        return {"sections": [{"code": "R3", "kind": "shelf", "allowed_categories": ["핸드크림"],
                              "slots": [sl("R3-1", r3[0]), sl("R3-2", r3[1])]},
                             {"code": "S", "kind": "staff", "allowed_categories": [], "slots": [sl("S-1", None)]}]}

    def test_slot_checks_against_storage_answer_key(self):
        ok = self.talk.slot_reserved("A", "A-X1", "핸드크림", "R3-1", ["핸드크림"], layout=self.lay())
        self.assertFalse(ok["flag"])
        skip = self.talk.slot_reserved("A", "A-X1", "핸드크림", "R3-2", ["핸드크림"], layout=self.lay())   # 오늘 고친 문제: R3-1 이 비었는데 R3-2
        self.assertIn("먼 줄 먼저", skip["wrong"])
        held = self.talk.slot_reserved("A", "A-X1", "핸드크림", "R3-2", ["핸드크림"], layout=self.lay(), held={"R3-1"})
        self.assertFalse(held["flag"])                             # R3-1 은 다른 물건이 회수하려고 잡아 둠 → 정상
        clash = self.talk.slot_reserved("A", "A-X1", "핸드크림", "R3-1", ["핸드크림"], layout=self.lay(("A-OLD", None)))
        self.assertIn("빈 칸", clash["wrong"])
        col = self.talk.slot_reserved("A", "A-X1", "립밤", "R3-1", ["핸드크림"], layout=self.lay())
        self.assertIn("품목 맞는 열", col["wrong"])

    def test_wait_checks_against_storage_answer_key(self):
        wrong = self.talk.slot_reserved("A", "A-X2", "핸드크림", None, None, wait_no=1, layout=self.lay())   # 정답지엔 빈 칸 → 이상
        self.assertIn("칸 대기 판단", wrong["wrong"])
        right = self.talk.slot_reserved("A", "A-X2", "핸드크림", None, None, wait_no=1, layout=self.lay(("A-1", "A-2")))
        self.assertFalse(right["flag"])

    def test_build_switch(self):
        self.assertIsNotNone(build_talk(self.rep, {}, sim=True))
        self.assertIsNone(build_talk(self.rep, {"TOWER_AGENT_TALK": "0"}, sim=True))
        self.assertIsNone(build_talk(self.rep, {}, sim=False))
        self.assertIsNotNone(build_talk(self.rep, {"TOWER_AGENT_TALK": "1"}, sim=False))

    def test_discord_agent_channel_has_no_fallback(self):
        self.assertEqual(CHANNELS["agent"][0], "DISCORD_WEBHOOK_AGENT")
        self.assertIn("agent", NO_FALLBACK)


class SimTalkTest(unittest.TestCase):
    def setUp(self):
        self.svc = build_sim_service(ENV)
        self.d = self.svc.sim

    def test_found_then_return_check_without_staged_help(self):
        self.d.found(FOUND)
        self.assertTrue(self.d.wait_idle())
        ev = agent_events(self.svc)
        scores = [e["agent"]["score"] for e in ev if e["agent"]["kind"] == "score"]
        self.assertTrue(scores and all(s == 100 for s in scores), scores)   # 맞는 답은 처음부터 100점(일부러 덜 채우지 않음)
        self.assertFalse(any(e["agent"]["kind"] in ("coach", "reflect", "retry", "learn") for e in ev))
        self.assertTrue(any(e["agent"]["from"] == "채점 에이전트" and "보관 칸" in e["body"] for e in ev))   # 보관 칸 답도 정답지로 채점
        self.assertTrue(all(e["agent"]["from"] == "메인 AI" or e["agent"]["to"] == "메인 AI" for e in ev))   # 모든 말은 메인 AI 를 거침
        r = self.d.lost("검정 립밤 잃어버렸어요 초량역에서요")
        self.assertTrue(self.d.wait_idle())
        ev3 = agent_events(self.svc)
        self.assertTrue(any(e["agent"]["from"] == "로봇팔 에이전트" and "범위 안" in e["body"] for e in ev3))
        self.assertEqual(self.svc.world.items[r["item_id"]]["status"], "인계 완료")
        sent = [m for m in self.svc.reporter.messages if m["channel"] == "agent"]
        self.assertEqual(len(sent), 2)                           # 습득 1 + 반환 1, 대화마다 한 번
        self.assertFalse([m for m in self.svc.reporter.messages if m["channel"] == "alert" and "답 확인 필요" in m["title"]])

    def test_unknown_item_is_flagged_for_staff(self):
        # 진짜 키오스크 사진에서 Qwen 이 품목을 못 읽은 경우(가상 습득은 품목 없는 말을 받지 않으므로 기록을 직접 만듦)
        iid = next(iter(self.svc.world.items))
        row = {**self.svc.world.db_get_item(iid), "features": {"category": "확인 불가", "color": "분홍"}}
        self.svc.talk.found_registered(iid, row, "중앙역 승강장")
        ev = agent_events(self.svc)
        self.assertTrue(any(e["agent"]["kind"] == "coach" and "품목" in e["body"] for e in ev))
        self.assertTrue([m for m in self.svc.reporter.messages if m["channel"] == "alert" and "답 확인 필요" in m["title"]])

    def test_off_switch_keeps_flow(self):
        svc = build_sim_service({**ENV, "TOWER_AGENT_TALK": "0"})
        self.assertIsNone(svc.talk)
        svc.sim.found(FOUND)
        self.assertTrue(svc.sim.wait_idle())
        r = svc.sim.lost("검정 립밤 잃어버렸어요 초량역에서요")
        self.assertTrue(svc.sim.wait_idle())
        self.assertEqual(svc.world.items[r["item_id"]]["status"], "인계 완료")
        self.assertFalse(any(e["channel"] == "agent" for e in svc.board.since(0, limit=999)))


if __name__ == "__main__":
    unittest.main()


class ApiPrivacyTest(unittest.TestCase):
    def test_public_story_endpoint_hides_agent_talk_but_admin_live_shows(self):
        from fastapi.testclient import TestClient
        from agents.api import build_app
        svc = build_sim_service(ENV)
        client = TestClient(build_app(svc))
        f = svc.sim.found(FOUND)
        self.assertTrue(svc.sim.wait_idle())
        pub = client.get(f"/sim/stories/{f['story_id']}").json()
        self.assertFalse(any(e["channel"] == "agent" for e in pub["events"]))
        live = client.get("/api/admin/live/state?after=0").json()
        self.assertTrue(any(e["channel"] == "agent" for e in live["events"]))


class DemoToolTest(unittest.TestCase):
    def test_demo_prints_three_conversations_without_sending(self):
        import io
        import contextlib
        from tools import agent_talk_demo
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(agent_talk_demo.main([]), 0)
        out = buf.getvalue()
        self.assertEqual(out.count("── T"), 3)
        self.assertIn("score", out)
        self.assertNotIn("reflect", out)                    # 11/11 일부러 만든 도움·되돌아보기 연출 없음
        self.assertIn("범위 안", out)

    def test_send_without_webhook_stops(self):
        from unittest import mock
        from tools import agent_talk_demo
        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_AGENT": ""}), mock.patch("tools.envfile.load_env", lambda *a, **k: None):
            self.assertEqual(agent_talk_demo.main(["--send"]), 2)
