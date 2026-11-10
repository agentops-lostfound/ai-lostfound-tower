"""챗봇 대화 접수(분실 접수·습득 신고) + 판단하는 supervisor (LF-5 · 11/9 변재원)

11/9 검토 의견: "기본 안내만 하면 supervisor 의 존재 의미가 없다" → 접수 일꾼(intake)을 더하고 supervisor 가 결과를 보고 판단한다.
"""
import os
import unittest

os.environ.setdefault("LF_LANGFUSE", "0")

from agents.chat_intake import IntakeAgent, IntakeSessions, check_action, detect_start, extract  # noqa: E402
from agents.chatbot import Chatbot  # noqa: E402
from agents.guidance import Guidance  # noqa: E402

ID = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-1******"}


class FakeDesk:
    """가상 시연 창구(SimDirector)와 같은 함수 이름·결과 모양"""

    def __init__(self, ask_first=False):
        self.calls, self.ask_first = [], ask_first

    def found(self, text):
        self.calls.append(("found", text))
        return {"item_id": "S-20261109-0007", "place_text": "서면역 5번 출구 앞", "story_id": "st1"}

    def lost(self, text, opts):
        self.calls.append(("lost", text, opts))
        if self.ask_first:
            return {"pending_id": "p1", "question": "물건에 붙은 스티커나 표시가 있다면 어떤 모양인가요?", "candidates": [{}, {}]}
        return {"claim_id": "C-20261109-0003", "item_id": "S-1", "quiz_passed": True, "story_id": "st2"}

    def answer(self, pid, text):
        self.calls.append(("answer", pid, text))
        return {"claim_id": "C-20261109-0004", "item_id": "S-2", "quiz_passed": False, "story_id": "st3"}


class RuleTest(unittest.TestCase):
    def test_detect_start(self):
        for q, want in [("분실 접수하기", "lost"), ("지갑 잃어버렸는데 접수해 주세요", "lost"), ("분실 신고 하고 싶어요", "lost"),
                        ("주운 물건 신고하고 싶어요", "found"), ("습득 신고하기", "found"), ("지갑 주웠는데 맡기고 싶어요", "found"),
                        ("검정 지갑 잃어버렸어요", None), ("본센터 어디예요?", None), ("주운 물건은 어떻게 신고하나요?", None),
                        ("분실 신고는 어디서 하나요?", None), ("분실 신고 하고 싶은데 어떻게 해요?", "lost")]:
            self.assertEqual(detect_start(q), want, q)

    def test_extract(self):
        self.assertEqual(extract("어제 저녁 서면에서 까만 반지갑", "lost"),
                         {"category": "지갑", "color": "검정", "station": "서면", "when": "어제 저녁"})
        self.assertEqual(extract("서면이요", "lost", "station"), {"station": "서면"})
        self.assertEqual(extract("모르겠어요", "lost", "when"), {"when": "모름"})
        self.assertEqual(extract("없어요", "lost", "detail"), {"detail": "없음"})
        self.assertEqual(extract("별 스티커 붙어 있어요", "lost", "detail")["detail"], "별 스티커")
        self.assertEqual(extract("5번 출구 앞", "found", "place")["place"], "5번 출구 앞")

    def test_identity_action_only_masked(self):
        self.assertEqual(check_action(ID), ID)
        self.assertIsNone(check_action(None))
        for bad in ({"type": "identity", "name_masked": "홍길동", "id_no_masked": "******-1******"},          # 가리지 않은 이름
                    {"type": "identity", "name_masked": "홍*동", "id_no_masked": "900101-1234567"},          # 주민번호 원문
                    {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-5******"},          # 성별 숫자 범위 밖
                    {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-1******", "x": 1},  # 모르는 칸
                    {"type": "other"}, "홍*동"):
            with self.assertRaises(ValueError, msg=str(bad)):
                check_action(bad)

    def test_session_expires(self):
        now = [0.0]
        s = IntakeSessions(ttl=10, clock=lambda: now[0])
        s.put("a", {"kind": "lost"})
        self.assertIsNotNone(s.get("a"))
        now[0] = 11
        self.assertIsNone(s.get("a"))


class AgentTest(unittest.TestCase):
    def test_lost_full_flow_needs_confirm(self):
        desk = FakeDesk()
        a = IntakeAgent(desk=desk)
        r = a.step("s1", "검정 지갑 서면에서 잃어버렸는데 접수해 주세요")
        self.assertEqual((r["status"], r["intake"]["asked"]), ("intake_question", "when"))       # 품목·색·역은 한 번에 채움
        r = a.step("s1", "어제")
        r = a.step("s1", "없어요")
        self.assertEqual(r.get("form"), {"kind": "identity"})
        r = a.step("s1", "본인 확인 정보를 입력했어요", action=ID)
        self.assertEqual(r["status"], "intake_confirm")
        self.assertEqual(desk.calls, [])                       # 확인 전에는 접수하지 않음
        r = a.step("s1", "음 잠깐만요")                         # 확인이 아닌 말 → 다시 확인 요청, 여전히 접수 안 함
        self.assertEqual(r["status"], "intake_confirm")
        self.assertEqual(desk.calls, [])
        r = a.step("s1", "접수할게요")
        self.assertEqual(r["status"], "intake_done")
        self.assertIn("C-20261109-0003", r["answer"])
        kind, text, opts = desk.calls[0]
        self.assertEqual(text, "어제 서면역에서 검정 카드지갑 잃어버렸어요")
        self.assertEqual(opts, {"visit": "kiosk", "name_masked": "홍*동", "id_no_masked": "******-1******"})
        self.assertIsNone(a.active("s1"))                      # 끝나면 대화 상태를 지움

    def test_lost_quiz_question_from_desk(self):
        desk = FakeDesk(ask_first=True)
        a = IntakeAgent(desk=desk)
        a.step("s2", "분실 접수하기", prior=["갈색 지갑 잃어버렸어요"])      # 앞 대화의 품목·색을 다시 묻지 않음
        self.assertEqual(a.active("s2")["slots"], {"category": "지갑", "color": "갈색"})
        for q in ("해운대", "오늘", "없어요"):
            a.step("s2", q)
        a.step("s2", "확인", action=ID)
        r = a.step("s2", "네")
        self.assertEqual((r["status"], r["choices"][0]), ("intake_question", "모름"))
        r = a.step("s2", "별 스티커")
        self.assertEqual(desk.calls[-1], ("answer", "p1", "별 스티커"))
        self.assertIn("직원이 직접 확인", r["answer"])        # 11/10 키오스크 대신 직원 대면 확인으로 안내

    def test_found_flow_and_inactive_item(self):
        desk = FakeDesk()
        a = IntakeAgent(desk=desk)
        a.step("s3", "주운 물건 신고하고 싶어요")
        a.step("s3", "흰색 보조배터리")
        a.step("s3", "해운대")
        r = a.step("s3", "승강장")
        self.assertEqual(r["status"], "intake_confirm")
        r = a.step("s3", "접수할게요")
        self.assertEqual(desk.calls[0], ("found", "해운대역 승강장에서 흰색 보조배터리 주웠어요"))
        self.assertIn("S-20261109-0007", r["answer"])
        a.step("s4", "습득 신고하기")
        r = a.step("s4", "빨간 립밤")
        self.assertEqual(r["status"], "intake_failed")         # 운영하지 않는 품목은 접수하지 않음
        self.assertEqual(desk.calls[1:], [])

    def test_cancel_fix_and_no_desk(self):
        a = IntakeAgent(desk=None)
        a.step("s5", "분실 접수하기")
        self.assertEqual(a.step("s5", "취소")["status"], "intake_cancelled")
        self.assertIsNone(a.active("s5"))
        a.step("s6", "검정 지갑 서면에서 잃어버린 거 접수해 주세요")
        for q in ("어제", "없어요"):
            a.step("s6", q)
        a.step("s6", "확인", action=ID)
        r = a.step("s6", "고칠게요")                            # 고치기 → 물건 종류만 남기고 다시
        self.assertEqual(a.active("s6")["slots"], {"category": "지갑"})
        self.assertEqual(r["intake"]["asked"], "color")
        for q in ("검정", "서면", "어제", "없어요"):
            a.step("s6", q)
        a.step("s6", "확인", action=ID)
        r = a.step("s6", "접수할게요")
        self.assertEqual(r["status"], "intake_unavailable")    # 창구 없는 모드: 정리한 내용으로 키오스크·웹 안내
        self.assertIn("분실인 웹", r["answer"])

    def test_model_fill_is_checked(self):
        class Brain:
            def extract_slots(self, q, kind, schema):
                return {"category": "지갑", "color": "보라보라", "station": "부산"}   # 값 목록 밖 → 버림
        a = IntakeAgent(desk=FakeDesk(), brain=Brain())
        a.step("s7", "분실 접수하기")
        a.step("s7", "어제 지하상가 쪽에서 반으로 접는 그거")
        self.assertEqual(a.active("s7")["slots"].get("category"), "지갑")
        self.assertNotIn("color", a.active("s7")["slots"])


class SupervisorTest(unittest.TestCase):
    def bot(self, desk=None):
        from agents.chat_search import DemoItemDatabase, SearchAgent
        import tempfile
        db = DemoItemDatabase(os.path.join(tempfile.mkdtemp(), "demo.sqlite3"))
        return Chatbot(Guidance(), search=SearchAgent(db), intake=IntakeAgent(desk=desk or FakeDesk()))

    def test_intake_path_and_ask_user_decision(self):
        r = self.bot().ask("분실 접수하기", session_id="sv-1")
        self.assertEqual(r["agent"], "intake")
        self.assertEqual(r["agent_path"], ["coordinator", "planner", "supervisor", "intake", "supervisor", "reporter", "supervisor"])
        self.assertEqual(r["decisions"][-1]["decide"], "ask_user")

    def test_guidance_question_inside_intake(self):
        b = self.bot()
        b.ask("분실 접수하기", session_id="sv-2")
        r = b.ask("본센터 운영시간 알려줘", session_id="sv-2")
        self.assertIn("researcher", r["agent_path"])
        self.assertEqual(r["decisions"][0]["decide"], "add_guidance")
        self.assertIn("어떤 물건인가요", r["answer"])           # 안내 답 뒤에 접수 질문을 이어서

    def test_offer_intake_after_candidates(self):
        r = self.bot().ask("검정 지갑 잃어버렸어요", session_id="sv-3")
        if r.get("candidates"):
            self.assertIn("분실 접수하기", r["choices"])
            self.assertIn("offer_intake", [d["decide"] for d in r["decisions"]])

    def test_offer_found_intake_and_off_topic(self):
        r = self.bot().ask("주운 물건은 어디에 맡기나요?", session_id="sv-4")
        self.assertIn("습득 신고하기", r["choices"])
        r = self.bot().ask("맛집 찾아줘", session_id="sv-5")
        self.assertEqual(r["agent"], "guidance")
        self.assertFalse(r["item_search_performed"])


class SimEndToEndTest(unittest.TestCase):
    """가상 시연 진짜 창구(SimDirector)로 습득 신고 → 같은 물건 분실 접수 → 찾기 번호"""

    def test_found_then_lost_claim(self):
        os.environ["TOWER_SIM"] = "0"
        from agents.chat_api import build_chatbot_from_env
        from agents.chat_search import SimTowerItemSearch
        from agents.sim_director import build_sim_service
        os.environ.pop("LF_CHAT_RAG_MODEL", None)
        svc = build_sim_service({"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SEND": "0", "TOWER_AGENT_TALK": "0"})
        bot = build_chatbot_from_env(SimTowerItemSearch(svc.world.chat_items), desk=svc.sim)
        for q in ("주운 물건 신고하고 싶어요", "서면 5번 출구 앞에서 검정 지갑", "접수할게요"):
            r = bot.ask(q, session_id="e2e-found")
        self.assertEqual(r["status"], "intake_done")
        item = r["intake"]["item_id"]
        self.assertTrue(item.startswith("S-"))
        svc.sim.wait_idle(60)
        for q, act in (("서면에서 검정 지갑 잃어버린 거 접수해 주세요", None), ("오늘", None), ("없어요", None),
                       ("본인 확인 정보를 입력했어요", ID), ("접수할게요", None)):
            r = bot.ask(q, session_id="e2e-lost", intake_action=act)
            if r["status"] == "intake_question" and r["intake"]["stage"] == "quiz":
                r = bot.ask("모름", session_id="e2e-lost")
        self.assertEqual(r["status"], "intake_done", r["answer"])
        self.assertTrue(r["intake"]["claim_id"].startswith("C-"))
        self.assertEqual(r["intake"]["item_id"], item)          # 방금 습득 신고한 그 물건으로 찾기 요청



class ApiTest(unittest.TestCase):
    def test_intake_action_checked_by_api(self):
        try:
            from fastapi import FastAPI
            from fastapi.testclient import TestClient
        except ImportError:
            self.skipTest("fastapi 필요")
        from agents.chat_api import add_chat_routes
        bot = Chatbot(Guidance(), intake=IntakeAgent(desk=FakeDesk()))
        app = FastAPI()
        add_chat_routes(app, bot)
        c = TestClient(app)
        r = c.post("/chat/questions", json={"question": "분실 접수하기", "session_id": "api-test-0001"})
        self.assertEqual((r.status_code, r.json()["agent"]), (200, "intake"))
        bad = {"type": "identity", "name_masked": "홍길동", "id_no_masked": "******-1******"}
        r = c.post("/chat/questions", json={"question": "확인", "session_id": "api-test-0001", "intake_action": bad})
        self.assertEqual(r.status_code, 422)
        r = c.post("/chat/questions", json={"question": "확인", "session_id": "api-test-0001", "intake_action": ID})
        self.assertEqual(r.status_code, 200)
        self.assertIn("decisions", r.json())


if __name__ == "__main__":
    unittest.main()


class ReviewFixesTest(unittest.TestCase):
    """11/9 정연우 검토 반영: 분실인 먼저 신고(대기) · 확인 중복 클릭 · 초안 번호"""

    def test_double_confirm_registers_once(self):
        desk = FakeDesk()
        a = IntakeAgent(desk=desk)
        for q in ("주운 물건 신고하고 싶어요", "흰색 보조배터리", "해운대", "승강장"):
            a.step("d1", q)
        first = a.step("d1", "접수할게요")
        again = a.step("d1", "접수할게요")                   # 두 번째 클릭
        self.assertEqual([c[0] for c in desk.calls], ["found"])
        self.assertIn("이미 접수했어요", again["answer"])
        self.assertIn(first["intake"]["item_id"], again["answer"])
        self.assertIsNone(a.active("d1"))                     # 끝난 접수는 진행 중이 아님
        self.assertTrue(a.wants("d1", "접수할게요"))
        self.assertFalse(a.wants("d1", "본센터 어디예요?"))

    def test_concurrent_confirm_registers_once(self):
        import threading
        import time as _t

        class SlowDesk(FakeDesk):
            def found(self, text):
                _t.sleep(0.2)
                return super().found(text)
        desk = SlowDesk()
        a = IntakeAgent(desk=desk)
        for q in ("주운 물건 신고하고 싶어요", "흰색 보조배터리", "해운대", "승강장"):
            a.step("d2", q)
        ts = [threading.Thread(target=a.step, args=("d2", "접수할게요")) for _ in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len([c for c in desk.calls if c[0] == "found"]), 1)

    def test_changed_draft_needs_new_confirm(self):
        desk = FakeDesk()
        a = IntakeAgent(desk=desk)
        for q in ("주운 물건 신고하고 싶어요", "흰색 보조배터리", "해운대", "승강장"):
            r = a.step("d3", q)
        v1 = r["intake"]["draft_version"]
        r = a.step("d3", "아 서면이었어요")                     # 확인 대기 중 값이 바뀜
        self.assertEqual(r["status"], "intake_confirm")
        self.assertGreater(r["intake"]["draft_version"], v1)
        self.assertIn("역 서면", r["answer"])
        self.assertEqual(desk.calls, [])

    def test_lost_first_then_found_links_claim(self):
        os.environ["TOWER_SIM"] = "0"
        from agents.chat_api import build_chatbot_from_env
        from agents.chat_search import SimTowerItemSearch
        from agents.sim_director import build_sim_service
        os.environ.pop("LF_CHAT_RAG_MODEL", None)
        svc = build_sim_service({"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SEND": "0", "TOWER_AGENT_TALK": "0"})
        bot = build_chatbot_from_env(SimTowerItemSearch(svc.world.chat_items), desk=svc.sim)
        for q, act in (("서면에서 빨간 핸드크림 잃어버린 거 접수해 주세요", None), ("오늘", None), ("없어요", None),
                       ("본인 확인 정보를 입력했어요", ID), ("접수할게요", None)):
            r = bot.ask(q, session_id="lf-wait", intake_action=act)
        self.assertEqual(r["status"], "intake_done", r["answer"])
        wid = r["intake"]["wait_id"]
        self.assertRegex(wid, r"^L-\d{8}-\d{4}$")
        r = bot.ask(f"{wid} 어떻게 됐어요?", session_id="lf-other")
        self.assertIn("아직", r["answer"])
        for q in ("주운 물건 신고하고 싶어요", "서면 5번 출구 앞에서 빨간 핸드크림", "접수할게요"):
            f = bot.ask(q, session_id="lf-found")
        self.assertEqual(f["status"], "intake_done", f["answer"])
        svc.sim.wait_idle(60)
        st = svc.sim.wait_status(wid)
        self.assertEqual(st["state"], "matched", st)
        self.assertEqual(st["item_id"], f["intake"]["item_id"])
        r = bot.ask(f"{wid} 어떻게 됐어요?", session_id="lf-other2")
        self.assertIn(st["claim_id"], r["answer"])

    def test_web_lost_without_identity_still_rejects(self):
        os.environ["TOWER_SIM"] = "0"
        from agents.sim_director import build_sim_service
        from agents.service import RequestError
        svc = build_sim_service({"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SEND": "0", "TOWER_AGENT_TALK": "0"})
        with self.assertRaises(RequestError):                 # 디스코드 봇처럼 본인 정보 없는 신고는 예전대로 거절
            svc.sim.lost("서면에서 빨간 핸드크림 잃어버렸어요")


class EvalFindingsTest(unittest.TestCase):
    """11/9 질문 500개 채점표(evaluation/chat_eval.py)가 찾은 문제 3가지"""

    def test_split_sentence_starts_intake(self):
        from agents.chat_intake import detect_start
        self.assertEqual(detect_start("서면 5번 출구 앞에서 검정 카드지갑 주웠어요. 신고할게요"), "found")
        self.assertEqual(detect_start("어제 갈색 지갑 잃어버렸어요. 접수해 주세요"), "lost")
        self.assertIsNone(detect_start("지갑 주웠어요. 신고는 어떻게 해요?"))          # 방법을 묻는 말은 안내로

    def test_correction_is_not_free_text_answer(self):
        from agents.chat_intake import extract
        out = extract("아 오늘 아침이었어요", "lost", want="detail")
        self.assertEqual(out.get("when"), "오늘 아침")
        self.assertNotIn("detail", out)
        self.assertNotIn("place", extract("아니 해운대에서 주웠어요", "found", want="place"))
        self.assertEqual(extract("뒷면에 고양이 그림", "lost", want="detail").get("detail"), "고양이 그림")

    def test_far_color_is_not_a_candidate(self):
        os.environ["TOWER_SIM"] = "0"
        from agents.sim_director import build_sim_service
        svc = build_sim_service({"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SEND": "0", "TOWER_AGENT_TALK": "0"})
        self.assertEqual(svc.sim.candidates({"category": "지갑", "color": "검정"}, "서면"), [])     # 기본 지갑은 갈색
        self.assertTrue(svc.sim.candidates({"category": "지갑", "color": "갈색"}, "서면"))
        self.assertTrue(svc.sim.candidates({"category": "모형폰", "color": "회색"}, None))          # 흰색과 비슷한 색은 남김


class EvalFindings2Test(unittest.TestCase):
    """11/9 채점표 두 번째 묶음: 후보 0개 접수 제안·운영 밖 물건·다른 종류 이야기·직원 관제 낱말"""

    def _bot(self):
        os.environ["TOWER_SIM"] = "0"
        from agents.chat_api import build_chatbot_from_env
        from agents.chat_search import SimTowerItemSearch
        from agents.sim_director import build_sim_service
        os.environ.pop("LF_CHAT_RAG_MODEL", None)
        svc = build_sim_service({"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_SEND": "0", "TOWER_AGENT_TALK": "0"})
        return build_chatbot_from_env(SimTowerItemSearch(svc.world.chat_items), desk=svc.sim)

    def test_zero_candidates_offers_lost_intake(self):
        r = self._bot().ask("검정 지갑 잃어버렸어요", session_id="lf-zero-01")
        self.assertEqual(r.get("candidates"), [])
        self.assertIn("분실 접수하기", r["choices"])
        self.assertIn("offer_intake", [d["decide"] for d in r["decisions"]])

    def test_other_item_is_not_taken(self):
        r = self._bot().ask("우산 분실 신고하고 싶어요", session_id="lf-other-01")
        self.assertEqual(r["status"], "intake_failed")
        self.assertIn("역무실", r["answer"])

    def test_opposite_story_does_not_change_slots(self):
        b = self._bot()
        b.ask("습득 신고할게요", session_id="lf-opp-01")
        b.ask("지갑", session_id="lf-opp-01")
        r = b.ask("근데 저도 휴대폰을 잃어버렸어요", session_id="lf-opp-01")
        self.assertIn("먼저 끝내거나", r["answer"])
        self.assertIn("물건 카드지갑", r["answer"])

    def test_staff_words(self):
        from agents.chatbot import is_ops_question
        for q in ("반환 보류된 거 있어?", "어디서 제일 많이 막혀?", "로봇 잡기 실패 몇 번 있었어?", "실패한 사례 번호만 알려줘"):
            self.assertTrue(is_ops_question(q), q)
        self.assertFalse(is_ops_question("보관 기간 알려줘"))
