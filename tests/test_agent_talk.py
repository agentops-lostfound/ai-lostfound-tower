"""11/9 에이전트 대화(agents/agent_talk.py) — 메인 AI 아래 요청·답·확인·채점·도움·되돌아보기·배운 점"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.agent_talk import AgentTalk, grade, build_talk, LESSON_FULL_RECORD, LESSON_SLOT_BOUNDS, PASS  # noqa: E402
from agents.live import LiveBoard, LiveReporter  # noqa: E402
from agents.sim_director import build_sim_service  # noqa: E402
from discord_ops.reporter import CHANNELS, NO_FALLBACK, Reporter  # noqa: E402

ENV = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}
FOUND = "초량역 5번 출구 앞에서 검정 카드지갑 주웠어요"


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

    def test_lesson_after_help_then_used(self):
        area = {"slot_id": "R2-1", "bounds_mm": [100, 100, 200, 200]}
        self.talk.robot_check("C1", "S-1", [150, 150], area)
        kinds1 = [e["agent"]["kind"] for e in self.board.since(0, limit=999) if e["channel"] == "agent"]
        self.assertTrue({"coach", "reflect", "retry"} <= set(kinds1))
        self.assertTrue(self.talk.knows("DB 에이전트", LESSON_SLOT_BOUNDS))
        last = self.board.last_seq
        self.talk.robot_check("C2", "S-1", [150, 150], area)
        kinds2 = [e["agent"]["kind"] for e in self.board.since(last, limit=999) if e["channel"] == "agent"]
        self.assertIn("learn", kinds2)
        self.assertNotIn("coach", kinds2)
        self.talk.reset()
        self.assertFalse(self.talk.knows("DB 에이전트", LESSON_SLOT_BOUNDS))

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

    def test_found_help_then_learned_then_return_check(self):
        self.d.found(FOUND)
        self.assertTrue(self.d.wait_idle())
        ev = agent_events(self.svc)
        scores = [e["agent"]["score"] for e in ev if e["agent"]["kind"] == "score" and "DB" in e["body"]]
        self.assertLess(scores[0], PASS)                         # 처음엔 접수 표만 읽어 부족
        self.assertEqual(scores[1], 100)                         # 도움 뒤 다시 답 → 100
        self.assertTrue(any(e["agent"]["kind"] == "reflect" for e in ev))
        self.assertTrue(self.svc.talk.knows("DB 에이전트", LESSON_FULL_RECORD))
        self.assertTrue(all(e["agent"]["from"] == "메인 AI" or e["agent"]["to"] in ("메인 AI", "채점 에이전트", "DB 에이전트")
                            for e in ev))                         # 모든 말은 메인 AI 를 거치거나 채점·도움 쌍
        last = self.svc.board.last_seq
        self.d.found("중앙역 2번 출구에서 파란 보조배터리 주웠어요")
        self.assertTrue(self.d.wait_idle())
        ev2 = [e for e in self.svc.board.since(last, limit=999) if e["channel"] == "agent"]
        self.assertTrue(any(e["agent"]["kind"] == "learn" for e in ev2))
        self.assertFalse(any(e["agent"]["kind"] == "coach" for e in ev2))
        r = self.d.lost("검정 카드지갑 잃어버렸어요 초량역에서요")
        self.assertTrue(self.d.wait_idle())
        ev3 = agent_events(self.svc)
        self.assertTrue(any(e["agent"]["from"] == "로봇팔 에이전트" and "범위 안" in e["body"] for e in ev3))
        self.assertEqual(self.svc.world.items[r["item_id"]]["status"], "인계 완료")
        sent = [m for m in self.svc.reporter.messages if m["channel"] == "agent"]
        self.assertEqual(len(sent), 3)                           # 습득 2 + 반환 1, 대화마다 한 번

    def test_reset_forgets_lessons(self):
        self.d.found(FOUND)
        self.assertTrue(self.d.wait_idle())
        self.d.reset()
        self.assertFalse(self.svc.talk.knows("DB 에이전트", LESSON_FULL_RECORD))

    def test_off_switch_keeps_flow(self):
        svc = build_sim_service({**ENV, "TOWER_AGENT_TALK": "0"})
        self.assertIsNone(svc.talk)
        svc.sim.found(FOUND)
        self.assertTrue(svc.sim.wait_idle())
        r = svc.sim.lost("검정 카드지갑 잃어버렸어요 초량역에서요")
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
        self.assertIn("reflect", out)                       # 도움 뒤 되돌아보기
        self.assertIn("범위 안", out)

    def test_send_without_webhook_stops(self):
        from unittest import mock
        from tools import agent_talk_demo
        with mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_AGENT": ""}), mock.patch("tools.envfile.load_env", lambda *a, **k: None):
            self.assertEqual(agent_talk_demo.main(["--send"]), 2)
