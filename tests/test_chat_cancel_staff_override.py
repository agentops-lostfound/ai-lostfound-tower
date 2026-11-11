"""11/10 남은 일 두 가지 — ① 챗봇 대화로 찾기 요청 취소 ② 직원 화면(/staff)의 '확인 질문 대신 직원 대면 확인' 칸.

① "C-… 취소해 주세요" / "찾기 요청 취소하고 싶어요" → 찾기 번호 → 본인 확인(가린 값) → [네] → 진짜 취소 입구(service.cancel_claim).
   방법만 묻는 말("예약 취소는 어떻게 해요?")은 지금처럼 안내 길. 신분 번호가 다르면 취소하지 않는다
② 직원 화면은 웹 확인 질문만 못 넘은 요청에 칸을 보이고, 세 현장 확인을 모두 체크했을 때만 staff_quiz_override 를 보낸다
"""
import os
import sys
import unittest
from chat_confirmation_helpers import ui_step, ui_ask

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ENV = {"TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0"}
OPT = {"visit": "kiosk", "name_masked": "홍*동", "id_no_masked": "******-1******"}
IDENT = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-1******"}
OTHER = {"type": "identity", "name_masked": "홍*동", "id_no_masked": "******-2******"}


def make():
    from agents.sim_director import build_sim_service
    svc = build_sim_service(ENV)
    return svc, svc.sim


class DetectTest(unittest.TestCase):
    def test_which_sentences_start_cancel(self):
        from agents.chat_intake import detect_start
        for q in ("C-20261110-0001 취소해 주세요", "찾기 요청 취소하고 싶어요", "방문 예약 취소할게요", "c-20261110-0003 철회"):
            self.assertEqual(detect_start(q), "cancel", q)
        for q in ("예약 취소는 어떻게 해요?", "지갑 갈색 찾아주시고 예약 취소 방법도 알려주세요", "예약한 날에 못 가면 어떻게 돼요?",
                  "분실 접수하고 싶어요", "취소"):
            self.assertNotEqual(detect_start(q), "cancel", q)
        self.assertEqual(detect_start("분실 접수하고 싶어요"), "lost")          # 원래 접수 길은 그대로


class ChatCancelTest(unittest.TestCase):
    def claim(self, d):
        r = d.lost("해운대역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))
        self.assertTrue(r.get("claim_id"), r)
        return r["claim_id"]

    def run_chat(self, a, sid, steps):
        out = None
        for q in steps:
            out = ui_step(a, sid, "" if isinstance(q, dict) else q, action=q if isinstance(q, dict) else None)
        return out

    def test_cancel_by_chat_with_number_in_first_message(self):
        from agents.chat_intake import IntakeAgent
        svc, d = make()
        cid = self.claim(d)
        a = IntakeAgent(desk=d)
        first = ui_step(a, "c1", f"{cid} 취소해 주세요", start="cancel")
        self.assertEqual(first["intake"]["asked"], "identity")             # 번호는 이미 읽음 → 본인 확인
        self.assertEqual(first.get("form"), {"kind": "identity"})
        conf = ui_step(a, "c1", "", action=IDENT)
        self.assertEqual(conf["status"], "intake_confirm")
        self.assertIn(cid, conf["answer"])
        self.assertEqual(svc.claims.get(cid)["status"], "booked")          # 확인 전에는 아무것도 바뀌지 않는다
        done = ui_step(a, "c1", "네")
        self.assertEqual(done["status"], "intake_done", done["answer"])
        self.assertEqual(svc.claims.get(cid)["status"], "cancelled")
        item = done["intake"]["item_id"]
        self.assertEqual(svc.world.items[item]["status"], "본센터 보관")   # 물건은 그대로 보관
        again = ui_step(a, "c1", "네")                                          # 확인을 또 눌러도 다시 취소하지 않음
        self.assertIn("이미", again["answer"])

    def test_number_asked_when_missing(self):
        from agents.chat_intake import IntakeAgent
        svc, d = make()
        cid = self.claim(d)
        a = IntakeAgent(desk=d)
        first = ui_step(a, "c2", "찾기 요청 취소하고 싶어요", start="cancel")
        self.assertEqual(first["intake"]["asked"], "claim_id")
        self.assertIn("찾기 번호", first["answer"])
        out = self.run_chat(a, "c2", [f"번호는 {cid.lower()} 이에요", IDENT, "네"])
        self.assertEqual(out["status"], "intake_done", out["answer"])
        self.assertEqual(svc.claims.get(cid)["status"], "cancelled")

    def test_wrong_identity_does_not_cancel(self):
        from agents.chat_intake import IntakeAgent
        svc, d = make()
        cid = self.claim(d)
        a = IntakeAgent(desk=d)
        out = self.run_chat(a, "c3", [f"{cid} 취소해 주세요", OTHER, "네"])
        self.assertEqual(out["status"], "intake_failed")
        self.assertIn("신분 번호가 맞지 않습니다", out["answer"])
        self.assertEqual(svc.claims.get(cid)["status"], "booked")

    def test_saying_no_keeps_claim(self):
        from agents.chat_intake import IntakeAgent
        svc, d = make()
        cid = self.claim(d)
        a = IntakeAgent(desk=d)
        out = self.run_chat(a, "c4", [f"{cid} 취소해 주세요", IDENT, "아니요"])
        self.assertEqual(out["status"], "intake_cancelled")
        self.assertIn("그대로", out["answer"])
        self.assertEqual(svc.claims.get(cid)["status"], "booked")

    def test_unknown_number_and_no_desk(self):
        from agents.chat_intake import IntakeAgent
        _, d = make()
        out = self.run_chat(IntakeAgent(desk=d), "c5", ["C-20991231-0099 취소해 주세요", IDENT, "네"])
        self.assertEqual(out["status"], "intake_failed")
        self.assertIn("없는 찾기 번호", out["answer"])
        out = self.run_chat(IntakeAgent(desk=None), "c6", ["C-20991231-0099 취소해 주세요", IDENT, "네"])
        self.assertEqual(out["status"], "intake_unavailable")

    def test_chatbot_routes_cancel_to_intake(self):
        import tempfile
        from agents.chat_intake import IntakeAgent
        from agents.chat_search import DemoItemDatabase, SearchAgent
        from agents.chatbot import Chatbot
        from agents.guidance import Guidance
        svc, d = make()
        cid = self.claim(d)
        bot = Chatbot(Guidance(), search=SearchAgent(DemoItemDatabase(os.path.join(tempfile.mkdtemp(), "demo.sqlite3"))),
                      intake=IntakeAgent(desk=d))
        r = ui_ask(bot, f"{cid} 취소해 주세요", session_id="web-c7")
        self.assertEqual(r["status"], "intake_question", r)
        self.assertEqual(r["intake"]["kind"], "cancel")
        self.assertIn("intake", r.get("agent_path", []) or [r.get("agent")])
        r = ui_ask(bot, "본인 확인", session_id="web-c7", intake_action=IDENT)
        self.assertEqual(r["status"], "intake_confirm", r)
        r = ui_ask(bot, "네", session_id="web-c7")
        self.assertEqual(r["status"], "intake_done", r)
        self.assertEqual(svc.claims.get(cid)["status"], "cancelled")
        g = ui_ask(bot, "예약 취소는 어떻게 해요?", session_id="web-c8")      # 방법만 묻는 말은 안내 그대로
        self.assertNotEqual(g["status"], "intake_question")


class StaffPageOverrideTest(unittest.TestCase):
    """직원 화면은 코드가 아니라 HTML 이라 글로 확인한다(서버 쪽 규칙은 test_claim_cancel_visit 에서 확인)"""

    def test_staff_page_has_override_box_and_guards(self):
        with open(os.path.join(ROOT, "web", "staff-desk", "index.html"), encoding="utf-8") as f:
            html = f.read()
        self.assertIn('id="g4row" hidden', html)                           # 기본은 숨김
        self.assertIn("!c.web_gates.quiz_passed", html)                     # 확인 질문만 못 넘은 요청에만 보임
        self.assertIn("c.web_gates.consent && c.web_gates.id_verified", html)
        self.assertIn("body.staff_quiz_override = true", html)
        self.assertIn('$("g1").checked && $("g2").checked && $("g3").checked', html)   # 세 칸을 모두 확인했을 때만

    def test_server_rules_for_the_override_box(self):
        from agents.service import RequestError
        base = {"visitor_id_match": True, "inner_feature_ok": True, "staff_confirmed": True}

        def failed_claim():
            svc, d = make()
            r = d.lost("서면역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))      # 역을 틀리게 말함 → 확인 질문 미통과
            self.assertFalse(r["quiz_passed"])
            return svc, r["claim_id"]

        svc, cid = failed_claim()
        out = svc.start_return({"claim_id": cid, **base})                     # 칸을 안 쓰면 반환하지 않음
        self.assertNotEqual(out["decision"], "returned")
        svc, cid = failed_claim()
        with self.assertRaises(RequestError):                                 # 세 칸 중 하나라도 빠지면 대신 확인을 받지 않음
            svc.start_return({"claim_id": cid, **base, "staff_confirmed": False, "staff_quiz_override": True})
        out = svc.start_return({"claim_id": cid, **base, "staff_quiz_override": True})
        self.assertEqual(out["decision"], "returned", out)


if __name__ == "__main__":
    unittest.main()


class StaffOverrideHandoverTest(unittest.TestCase):
    """11/10 사람 조작 점검: 확인 질문이 틀린 요청을 직원 대면 확인으로 진행하면 교차 검증 칸에 그 사실과 분실인이 말한 역이 보인다.
    본센터 키오스크 거절 문구는 '역무실'이 아니라 바로 옆 본센터 직원으로 안내한다"""

    def test_handover_queue_shows_quiz_and_station(self):
        svc, d = make()
        r = d.lost("부산역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))
        self.assertFalse(r["quiz_passed"], r)
        with self.assertRaises(Exception) as e:
            d.kiosk_return({"claim_id": r["claim_id"], "id_no_masked": "******-1******", "machine_id": "CENTER"})
        self.assertIn("본센터 직원", str(e.exception))
        self.assertNotIn("역무실", str(e.exception))
        d.staff_visit(r["claim_id"])
        q = [x for x in svc.handover_queue() if x["claim"] and x["claim"]["claim_id"] == r["claim_id"]]
        self.assertEqual(len(q), 1)
        self.assertIs(q[0]["claim"]["quiz_passed"], False)
        self.assertEqual(q[0]["claim"]["lost_station"], "부산")
        self.assertNotIn("id_no_masked", q[0]["claim"])                    # 가린 신분 번호는 보내지 않는다

    def test_staff_page_shows_rows(self):
        html = open(os.path.join(ROOT, "web", "staff-desk", "index.html"), encoding="utf-8").read()
        self.assertIn("분실인이 말한 역", html)
        self.assertIn("직원 대면 확인으로 진행한 요청", html)
        self.assertIn("function localTime", html)


class UnattendedHandoverTest(unittest.TestCase):
    """11/11 정상 흐름은 직원 없이(분실인이 제출보관함에서 꺼내고 키오스크 [물건 받았어요]) — 예외는 직원에게 남는다"""

    def test_override_case_stays_with_staff(self):
        svc, d = make()
        r = d.lost("부산역에서 분홍 핸드크림 잃어버렸어요", dict(OPT))
        out = d.staff_visit(r["claim_id"])
        self.assertEqual(out["decision"], "returned")
        with self.assertRaises(Exception) as e:
            d.kiosk_handover({"machine_id": "CENTER", "claim_id": r["claim_id"], "id_no_masked": "******-1******"})
        self.assertEqual(getattr(e.exception, "kind", None), "staff")
        q = [x for x in svc.handover_queue() if x["case_id"] == out["case_id"]]
        self.assertFalse(q[0]["self_pickup"])                                 # 직원 화면에서 '확인 시작'

    def test_kiosk_page_has_pickup_button(self):
        html = open(os.path.join(ROOT, "web", "kiosk", "index.html"), encoding="utf-8").read()
        self.assertIn('id="rgot"', html)
        self.assertIn("/api/kiosk/handover", html)
        self.assertNotIn("제출보관함 앞에서 직원이 신분증과 물건을 한 번 더 확인", html)
