"""11/8 질문-답 맞물림 검사(agents/chat_rag.py answer_gap) — 근거는 맞아도 물어본 것에 답하지 않는 경우
실측 문장: 11/8 집 PC "주운 사람 연락처 알려줄 수 있어요?", 11/7 40문항(evaluation 실행 결과)"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_rag import GAP_LEAD, GroundedRag, answer_gap  # noqa: E402
from agents.guidance import Guidance  # noqa: E402

FINDER_Q = "주운 사람 연락처 알려줄 수 있어요?"
FINDER_EV = "습득자 연락처 규칙은 물건이 인계 완료된 뒤 30일이 지나면 지우는 것입니다"
FINDER_SEN = "습득자 연락처는 물건 인계 후 30일이 지나면 삭제됩니다."
# 근거 문단에 되는지/안 되는지 답이 없는 질문(로봇팔이 직접 건네지 않고 직원이 건넴 — "안 된다"는 말이 문단에 없음)
ROBOT_Q = "로봇팔이 물건을 직접 손에 건네줄 수 있어요?"
ROBOT_EV = "로봇팔이 보관함에서 물건을 꺼내 제출보관함(물건 받는 칸)에 놓아요"
ROBOT_SEN = "로봇팔이 보관함에서 물건을 꺼내 제출보관함에 놓아요."

# 11/7 40문항 실측에서 맞게 답한 것(검사가 괜히 걸면 안 됨)
GOOD = [("신분증 꼭 가져가야 해?", "분실물을 찾기 위해 신분증을 가져가야 해요."),
        ("인증이 안 되면 받을 수 있어요?", "인증이 안 되면 반환 절차를 진행하지 않고 안내 후 종료됩니다."),
        ("분실 확인은 웹에서도 돼?", "분실물 확인은 모든 역 키오스크, 분실인 웹, 이 챗봇에서 할 수 있어요."),
        ("설명 칸에 전화번호 적어도 돼요?", "설명 칸에는 개인정보를 적지 마세요."),
        ("오늘 맡긴 거 바로 받을 수 있나요?", "맡긴 물건은 1시간마다 본센터로 옮겨집니다. 본센터 도착 전에는 바로 받을 수 없습니다."),
        ("습득자 연락처 언제 지워요?", "습득자 연락처는 물건 인계 완료 후 30일이 지나면 삭제됩니다."),
        ("키오스크 어디 있어요?", "해운대역과 서면역에 키오스크가 있어요. 부산역에 본센터가 있어요."),
        ("지갑 주웠는데 어디에 맡겨요?", "가까운 역의 키오스크에서 습득물을 신고할 수 있어요."),
        ("물건을 잃어버렸는데 어떻게 해야 돼요?", "분실물 확인은 모든 역 키오스크, 분실인 웹, 이 챗봇에서 할 수 있어요."),
        ("휴대폰은 상자에 어떻게 넣어요?", "휴대폰은 케이스 뒷면이 위로 가게 놓아야 해요."),
        ("물건 수령 절차 알려줘", "신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요.")]


def model(*replies, log=None):
    queue = list(replies)

    def request(payload):
        if log is not None:
            log.append(json.loads(payload["messages"][1]["content"]))
        if not queue:
            raise OSError("down")
        return {"message": {"content": json.dumps(queue.pop(0))}}
    return request


def say(ev, sen, **extra):
    return {"mode": "answer", "passage_ids": [0], "sentences": [{"evidence": ev, "sentence": sen}], **extra}


class AnswerGapTest(unittest.TestCase):
    def test_measured_good_answers_pass(self):
        for q, a in GOOD:
            self.assertIsNone(answer_gap(q, a), q)

    def test_measured_misses_are_caught(self):
        self.assertEqual(answer_gap(FINDER_Q, FINDER_SEN + " 연락처 보관은 습득자에게만 해당됩니다."), "yesno")
        self.assertEqual(answer_gap("지갑은 어느 쪽이 위로 가게 놓나요?", "휴대폰은 케이스의 뒷면이 위로 가게 놓아야 합니다."), "subject")
        self.assertEqual(answer_gap("보관 기간은 얼마나 돼요?", "본센터에서 보관해요."), "when")
        self.assertEqual(answer_gap("언제 본센터에 도착해요?", "직원이 본센터로 옮겨요."), "when")
        self.assertEqual(answer_gap("어디서 받아요?", "신분 확인 후 받으실 수 있어요."), "where")

    def test_retry_fixes_answer(self):
        """11/7 실측: 지갑을 물었는데 휴대폰 이야기 → 고칠 점을 받고 지갑 근거로 다시 씀"""
        log = []
        q = "지갑은 어느 쪽이 위로 가게 놓나요?"
        req = model(say("휴대폰은 케이스(뒷면)가 위로", "휴대폰은 케이스 뒷면이 위로 가게 놓아야 해요."),
                    say("지갑은 펼치지 말고 앞면이 위로 오게 두면 돼요", "지갑은 펼치지 말고 앞면이 위로 오게 두면 돼요.", answerable=True), log=log)
        r = GroundedRag(Guidance(), "m", request=req).ask(q)
        self.assertEqual(r["generation_status"], "generated")
        self.assertIn("지갑은", r["answer"])
        self.assertNotIn(GAP_LEAD, r["answer"])
        self.assertTrue(r["generation_note"].startswith("retry:subject"), r)
        self.assertNotIn("feedback", log[0])
        self.assertIn("지갑", log[1]["feedback"]["problem"])             # 모델에게 무엇이 빠졌는지 알려 줌
        self.assertIn("휴대폰", log[1]["feedback"]["previous_answer"])

    def test_retry_cannot_invent_policy(self):
        """근거 문단에 없는 '안 된다'를 다시 쓴 답이 지어내면 근거 없는 부정이라 버리고, 자료에 없다고 말함"""
        req = model(say(ROBOT_EV, ROBOT_SEN), say(ROBOT_EV, "로봇팔이 직접 건네줄 수는 없어요.", answerable=True))
        r = GroundedRag(Guidance(), "m", request=req).ask(ROBOT_Q)
        self.assertTrue(r["answer"].startswith(GAP_LEAD), r["answer"])
        self.assertIn("제출보관함", r["answer"])
        self.assertIn("not_addressed:yesno", r["generation_note"])

    def test_model_says_not_in_passages(self):
        req = model(say(ROBOT_EV, ROBOT_SEN),
                    say("직원이 실물 신분증과 물건을 한 번 더 확인", "직원이 실물 신분증과 물건을 한 번 더 확인해요.", answerable=False))
        r = GroundedRag(Guidance(), "m", request=req).ask(ROBOT_Q)
        self.assertTrue(r["answer"].startswith(GAP_LEAD), r["answer"])
        self.assertNotIn("신분증", r["answer"])                           # 11/8 실측: 다시 쓴 답의 문장은 안 씀(첫 답 사용)
        self.assertIn("제출보관함", r["answer"])                           # 관련 근거는 그대로 알려 줌
        self.assertIn("not_addressed:yesno", r["generation_note"])

    def test_retry_failure_still_honest(self):
        r = GroundedRag(Guidance(), "m", request=model(say(ROBOT_EV, ROBOT_SEN))).ask(ROBOT_Q)   # 두 번째 호출은 연결 오류
        self.assertTrue(r["answer"].startswith(GAP_LEAD) or r["generation_status"] != "generated", r)

    def test_finder_contact_is_never_shared(self):
        """11/8 사용자 결정: 습득자 연락처는 분실인에게 알려 주지 않음(DB 설계: 별도 표, 직원만 열람) — 모델 없이 정해진 문장"""
        def no_model(_payload):
            raise AssertionError("개인정보 질문은 모델을 부르지 않아야 함")
        for q in (FINDER_Q, "습득자 전화번호 알 수 있나요?", "주운 사람한테 감사 인사하고 싶은데 연락처 받을 수 있어요?", "주운 사람 누군지 알려줘"):
            r = GroundedRag(Guidance(), "m", request=no_model).ask(q)
            self.assertEqual(r["generation_status"], "fixed_policy_text", q)
            self.assertIn("알려 드리지 않아요", r["answer"])
        r = GroundedRag(Guidance(), None).ask("습득자 연락처 언제 지워요?")      # 삭제 시기 질문은 기존 규칙 그대로
        self.assertNotIn("알려 드리지 않아요", r["answer"])
        self.assertIn("30일", r["answer"])

    def test_no_retry_when_answer_fits(self):
        log = []
        req = model(say("신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요", "신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요."), log=log)
        r = GroundedRag(Guidance(), "m", request=req).ask("물건 수령 절차 알려줘")
        self.assertEqual(r["generation_status"], "generated")
        self.assertEqual(len(log), 1)


if __name__ == "__main__":
    unittest.main()
