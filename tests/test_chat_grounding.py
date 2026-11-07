"""11/8 근거 인용형 답 검사(agents/chat_rag.py grounded_sentences) — 실측에서 나온 실제 문장으로"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.chat_rag import GroundedRag, grounded_sentences, role_swapped  # noqa: E402
from agents.guidance import Guidance  # noqa: E402

PICKUP = "분실인 웹이나 키오스크에서 물건을 확인해 찾기 번호를 받은 뒤, 신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요."
FINDER = "프로젝트 DB 설계의 습득자 연락처 규칙은 물건이 인계 완료된 뒤 30일이 지나면 지우는 것입니다."
IDENT = "프로젝트 DB 설계에서 분실인 찾기 요청에는 동의 시각, 가린 이름·번호, 물건 설명과 분실 날짜·장소를 기록합니다."
CONSENT = "프로젝트 설계에서는 동의를 거부하거나 본인인증에 실패하면 반환 절차를 진행하지 않고 안내 후 종료합니다."


def one(evidence, sentence, question=""):
    return grounded_sentences([{"evidence": evidence, "sentence": sentence}], [PICKUP, FINDER, IDENT, CONSENT], question)


class GroundedSentenceTest(unittest.TestCase):
    def test_keeps_natural_paraphrase(self):
        for ev, sen, q in [(PICKUP, "찾기 번호를 받은 뒤 신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요.", "수령 절차"),
                           (FINDER, "습득자 연락처는 물건 인계 완료 후 30일이 지나면 삭제됩니다.", "습득자 연락처 언제 지워요?"),
                           (CONSENT, "본인인증에 실패하면 반환 절차를 진행하지 않습니다.", "인증이 안돼요"),
                           (PICKUP, "네, 신분증을 가지고 부산역 본센터 키오스크로 오셔야 해요.", "신분증 가져가야 해?")]:
            kept, dropped = one(ev, sen, q)
            self.assertEqual(kept, [sen], dropped)

    def test_drops_known_slips(self):
        cases = [(IDENT, "신분증 정보는 프로젝트 DB에 저장하지 않습니다.", "근거에 없는 부정"),            # 11/7 단정
                 (PICKUP, "습득자는 분실물 확인 후 부산역 본센터 키오스크로 와야 합니다.", "사람이 바뀜"),       # 11/8 실측
                 (CONSENT, "본인인증이 정상적으로 작동하는지 확인해보시기 바랍니다.", "근거에 없는 내용"),   # 근거 없는 조언
                 ("직원이 실물 신분증과 물건을 한 번 더 확인", "직원이 실물 신분증과 물건을 한 번 더 확인한 후 건네드려요.", "인용이 문단에 없음")]
        for ev, sen, why in cases:
            kept, dropped = one(ev, sen)
            self.assertEqual(kept, [], sen)
            self.assertTrue(dropped[0].startswith(why), dropped)

    def test_short_natural_answers_and_trimmed_quote(self):
        """11/8: 겹침이 적어도 맞는 짧은 답은 살리고, 구절 끝이 문단과 조금 달라도(다음 문장까지 이어 씀) 앞부분이 맞으면 인정"""
        kept, dropped = one(PICKUP, "필요한 준비물은 신분증이에요.", "그럼 거기 갈 때 뭐 챙겨요?")
        self.assertEqual(len(kept), 1, dropped)
        kept, dropped = one(PICKUP[:-3] + "요. 본센터 키오스크에서는", "신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요.")
        self.assertEqual(len(kept), 1, dropped)
        kept, dropped = one("본센터 키오스크에서는 직원이 한 번 더 확인", "직원이 한 번 더 확인해요.")     # 앞 대화 답에서 옮긴 구절
        self.assertEqual(kept, [])

    def test_role_swap(self):
        self.assertTrue(role_swapped("주운 사람이 본센터로 와야 해요", PICKUP))
        self.assertFalse(role_swapped("분실인은 본센터로 와요", PICKUP))
        self.assertFalse(role_swapped("본센터로 오시면 돼요", PICKUP))        # 사람을 말하지 않으면 바꾼 것 아님

    def test_rag_uses_sentences_and_falls_back_when_all_dropped(self):
        def fake(content):
            return lambda payload: {"message": {"content": json.dumps(content)}}
        good = {"mode": "answer", "passage_ids": [0],
                "sentences": [{"evidence": "신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요", "sentence": "신분증을 가지고 부산역 본센터 키오스크로 오시면 돼요."},
                              {"evidence": "신분증을 가지고", "sentence": "주운 사람이 신분증을 가지고 와요."}]}
        r = GroundedRag(Guidance(), "m", request=fake(good)).ask("물건 수령 절차 알려줘")
        self.assertEqual(r["generation_status"], "generated")
        self.assertNotIn("주운 사람", r["answer"])
        self.assertIn("dropped", r.get("generation_note", ""))
        bad = {"mode": "answer", "passage_ids": [0], "sentences": [{"evidence": "없는 구절입니다 정말로", "sentence": "아무 말이나 지어낸 문장이에요."}]}
        r = GroundedRag(Guidance(), "m", request=fake(bad)).ask("물건 수령 절차 알려줘")
        self.assertNotEqual(r["generation_status"], "generated")
        self.assertIn("No grounded sentence", r.get("generation_note", ""))


if __name__ == "__main__":
    unittest.main()
