"""11/8 관제탑 메인 AI(agents/tower_brain.py) 시험 — 매칭이 애매할 때 에이전트들과 근거를 모으고, 진행 여부는 코드 기준 그대로"""
import json
import os
import sys
import unittest
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.contracts import DECISION_RETURNED, DECISION_STAFF, UNKNOWN  # noqa: E402
from agents.supervisor import ReturnRequest, run_return  # noqa: E402
from agents.tools import MockBackend  # noqa: E402
from discord_ops.reporter import Reporter  # noqa: E402

W1 = {"color": "검정", "shape": "반지갑", "mark": "별 모양 스티커", "visible_text": "ABC", "material": "가죽"}
BLURRY = {**W1, "mark": UNKNOWN, "visible_text": UNKNOWN}           # 첫 촬영: 스티커·글자를 못 읽음
OTHER = {**W1, "mark": "없음", "visible_text": "없음"}               # 같은 검정 반지갑이지만 스티커 없음


@dataclass
class RecheckBackend(MockBackend):
    """첫 탑뷰는 특징을 못 읽고(두 지갑이 똑같아 보임), 두 번째 탑뷰는 제대로 읽는 가짜 부품"""
    second: list = field(default_factory=list)
    shots: int = 0

    def vision_topview(self):
        self.shots += 1
        if self.shots == 2 and self.second:
            self.bin_items = self.second
        return super().vision_topview()


def items(feats, xs=(100, 300)):
    return [{"object_id": f"X{i}", "features": f, "center": [x, 200]} for i, (f, x) in enumerate(zip(feats, xs))]


def recheck_backend(second=True):
    return RecheckBackend(bin_items=items((BLURRY, dict(BLURRY))), db={"A-1": {"status": "본센터 보관", "features": W1}},
                          second=items((W1, OTHER)) if second else [])


def brain(model_answers=None, slot=None, log=None):
    from agents.tower_brain import TowerBrain
    answers = list(model_answers or [])

    def request(payload):
        if log is not None:
            log.append(json.loads(payload["messages"][1]["content"]))
        if not answers:
            raise OSError("down")
        return {"message": {"content": json.dumps(answers.pop(0))}}
    return TowerBrain(model="m" if model_answers is not None else None, request=request if model_answers is not None else None,
                      slot_lookup=(lambda _id: slot))


def run(be, b):
    rep = Reporter(dry_run=True)
    out = run_return(ReturnRequest("C-1", "A-1"), be, rep, consult=b.consult if b else None)
    return out, [m for m in rep.messages if "🤖" in m["title"]]


class TowerBrainTest(unittest.TestCase):
    def test_without_brain_unchanged(self):
        out, talk = run(recheck_backend(), None)
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertEqual(talk, [])

    def test_vision_recheck_resolves_and_robot_continues(self):
        be = recheck_backend()
        out, talk = run(be, brain())                      # 모델 없음 → 정해진 순서(매칭 → 보관 칸 → 비전)
        self.assertEqual(out.decision, DECISION_RETURNED)
        self.assertIn("메인 AI 재확인", out.steps)
        self.assertEqual(out.matched_index, 0)
        who = [m["title"].split("🤖 ")[1] for m in talk]
        self.assertEqual(who[0], "메인 AI")
        for agent in ("매칭 에이전트", "보관 칸 에이전트", "비전 에이전트"):
            self.assertIn(agent, who)
        self.assertIn("반환을 계속", talk[-1]["body"])

    def test_unresolved_goes_to_staff_with_recommendation(self):
        be = recheck_backend(second=False)
        slot = {"slot_id": "R1-2", "bounds_mm": [0, 0, 200, 400]}     # 1번 후보(x=100)만 기록 칸 구역 안
        out, talk = run(be, brain(slot=slot))
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertFalse(be.robot_moved())
        self.assertIn("추천: 후보 1번", out.reason)
        self.assertIn("R1-2", " ".join(m["body"] for m in talk))

    def test_model_picks_order_and_invalid_answer_falls_back(self):
        log = []
        b = brain(model_answers=[{"next": "vision_agent", "reason": "가려졌을 수 있어 다시 촬영"}], log=log)
        out, talk = run(recheck_backend(), b)
        self.assertEqual(out.decision, DECISION_RETURNED)
        self.assertEqual(b.last["asked"][0], "vision_agent")            # 모델이 고른 순서
        self.assertEqual(b.last["routing"], "model")
        self.assertIn("다시 촬영", talk[1]["body"])
        b2 = brain(model_answers=[{"next": "finish", "reason": "끝"}])   # 근거 없이 바로 끝내기 → 규칙 순서
        run(recheck_backend(second=False), b2)
        self.assertEqual(b2.last["asked"][0], "matching_agent")

    def test_reason_repeating_instructions_is_replaced(self):
        """11/8 집 PC 실측: Mi:dm 이 이유에 지시문을 되풀이 → 직원이 읽을 정해진 문장으로"""
        measured = "아직 보관 칸 기록과 위치가 맞는 후보를 확인하지 않았으므로 다음에 부를 것을 저장합니다."
        b = brain(model_answers=[{"next": "storage_agent", "reason": measured}, {"next": "vision_agent", "reason": "가려졌을 수 있어 다시 촬영"}])
        _, talk = run(recheck_backend(), b)
        bodies = " ".join(m["body"] for m in talk)
        self.assertNotIn("저장합니다", bodies)
        self.assertIn("보관 칸 기록으로 후보를 좁히려고", bodies)
        self.assertIn("가려졌을 수 있어 다시 촬영", bodies)          # 자연스러운 이유는 그대로
        from agents.tower_brain import clean_reason              # 11/8 2차: 비전을 고르며 보관 칸 예시를 베낀 이유 → 비전용 정해진 문장
        self.assertEqual(clean_reason("vision_agent", "두 후보 점수가 같아서 보관 칸 기록으로 좁히려고"), "다시 찍으면 가려진 특징이 보일 수 있어서")
        self.assertEqual(clean_reason("storage_agent", "보관 칸 기록과 위치가 맞는 후보를 확인하려고"), "보관 칸 기록과 위치가 맞는 후보를 확인하려고")

    def test_brain_cannot_force_robot_when_recheck_still_uncertain(self):
        be = recheck_backend(second=False)
        out, _ = run(be, brain(model_answers=[{"next": "vision_agent", "reason": "x"}, {"next": "finish", "reason": "y"}]))
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertFalse(be.robot_moved())

    def test_consult_error_goes_to_staff(self):
        def boom(*_a):
            raise RuntimeError("x")
        be = recheck_backend()
        out = run_return(ReturnRequest("C-2", "A-1"), be, Reporter(dry_run=True), consult=boom)
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertIn("메인 AI 오류", out.reason)
        self.assertFalse(be.robot_moved())

    def test_lookalike_still_checked_after_recheck(self):
        be = recheck_backend()
        be.db["B-9"] = {"status": "본센터 보관", "features": W1}      # 똑같이 생긴 다른 물건이 보관 중
        out, talk = run(be, brain())
        self.assertEqual(out.decision, DECISION_STAFF)
        self.assertFalse(be.robot_moved())

    def test_service_passes_consult_only_when_brain_set(self):
        from agents.service import TowerService
        seen = []

        def flow(req, be, rep, reviewer=None, consult=None):
            seen.append(consult)
            return run_return(req, be, rep, reviewer, consult)
        svc = TowerService(lambda: recheck_backend(), Reporter(dry_run=True), flow=flow)
        gates = dict.fromkeys(("consent", "id_verified", "quiz_passed", "visitor_id_match", "inner_feature_ok", "staff_confirmed"), True)
        svc.start_return({"case_id": "C-3", "item_id": "A-1", **gates})
        self.assertIsNone(seen[-1])
        svc.brain = brain()
        out = svc.start_return({"case_id": "C-4", "item_id": "A-1", **gates})
        self.assertIsNotNone(seen[-1])
        self.assertEqual(out["decision"], DECISION_RETURNED)


if __name__ == "__main__":
    unittest.main()


class SimSceneTest(unittest.TestCase):
    """가상 시연 #흐린촬영: 메인 AI 를 끄면 직원 확인, 켜면 에이전트들이 근거를 모아 다시 찍고 반환까지"""
    def run_scene(self, brain_on):
        from unittest import mock
        from agents.sim_director import build_sim_service
        env = {"TOWER_SIM_SEED": "full", "TOWER_SIM_SPEED": "0", "TOWER_GPU_LEASE": "0", "TOWER_BRAIN": brain_on,
               "LF_CHAT_RAG_MODEL": "", "TOWER_BRAIN_MODEL": ""}
        with mock.patch.dict(os.environ, env):
            svc = build_sim_service(env)
            r = svc.sim.lost("블루 모형폰 잃어버렸어요 #흐린촬영")
            self.assertTrue(svc.sim.wait_idle())
        talk = [e for e in svc.board.since(0) if "🤖" in e["title"]]
        return svc.board.story(r["story_id"])["result"], talk

    def test_blur_scene(self):
        res, talk = self.run_scene("0")
        self.assertFalse(res["ok"])
        self.assertIn("매칭 불확실", res["text"])
        self.assertEqual(talk, [])
        res, talk = self.run_scene("1")
        self.assertTrue(res["ok"], res)
        bodies = " ".join(e["body"] for e in talk)
        self.assertIn("R1-2", bodies)                    # 보관 칸 에이전트가 기록 칸으로 맞는 후보를 가리킴
        self.assertIn("확실해졌어요", bodies)
