"""질문에 필요 없는 검색·핵심 절차 누락·문서에 없는 답의 대체를 검사."""
import os
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_chat_color_multiturn import setUpModule, tearDownModule  # noqa: F401
from test_deerflow_langfuse import bot
from test_chat_answer_gap import model, say
from agents.chat_rag import GroundedRag, answer_gap, contact_optional_clear, generation_requirements
from agents.guidance import Guidance


class SearchProposingBrain:
    def coordinate(self, *a):
        return None

    def plan(self, *a):
        return ['item_search', 'guidance']

    def choose(self, *a):
        return None


class GuidanceQualityTest(unittest.TestCase):
    def test_rubric_accepts_equivalent_facts_but_rejects_opposite_answers(self):
        from evaluation.chat_eval import QUESTIONS, check_turn
        items = {q['no']: q for q in json.loads(Path(QUESTIONS).read_text(encoding='utf-8'))}
        def grade(no, answer):
            return check_turn(items[no]['turns'][0], 200, {'answer': answer, 'status': 'answered',
                              'generation_status': 'generated', 'agent_path': ['researcher']})
        self.assertEqual(grade(68, '연락처는 남겨도 되지만 필수는 아닙니다.'), [])
        self.assertEqual(grade(68, '연락처는 남겨도 되지만 필수는 아니에요.'), [])
        self.assertEqual(grade(138, '요약 확인 후 접수 버튼을 눌러야 합니다.'), [])
        self.assertTrue(grade(68, '연락처는 반드시 남겨야 합니다.'))
        self.assertTrue(grade(138, '확인 없이 바로 접수가 완료됩니다.'))

    def test_required_generation_concepts_are_present_in_evidence(self):
        q = '처음인데 뭐부터 하면 돼요?'
        self.assertEqual(generation_requirements(q, [{'text': '설명 확인 뒤 후보 검색을 합니다.'}]), [['검색', '후보']])
        self.assertEqual(generation_requirements(q, [{'text': '품목과 색을 입력합니다.'}]), [])
        self.assertEqual(generation_requirements('주운 사람 연락처도 남겨야 하나요?',
                                                [{'text': '연락처는 남기지 않아도 됩니다.'}]), [['남기지 않아도']])

    def test_item_mentioned_in_help_does_not_authorize_model_search(self):
        b = bot(SearchProposingBrain())
        for q in ('지갑 안에 신분증이 다 들어 있어서 없는데요',
                  '휴대폰은 상자에 어떻게 놓아요?', '지갑 받을 때 필요한 신분증은 뭐예요?',
                  '지갑 안에 면허증이 들어 있어서 없어요'):
            r = b.ask(q)
            self.assertNotIn('item_search', r['agent_path'], q)
            self.assertIn('researcher', r['agent_path'])

    def test_explicit_search_with_help_keeps_both_workers(self):
        r = bot(SearchProposingBrain()).ask('검정 지갑 찾아줘 그리고 받을 때 필요한 신분증도 알려줘')
        self.assertIn('item_search', r['agent_path'])
        self.assertIn('researcher', r['agent_path'])

    def test_first_visit_answer_must_keep_next_search_step(self):
        ev = '왼쪽 물건 설명에 품목·색·특징을 적고 분실 날짜·호선·역을 입력한 뒤 설명 정리하기를 누릅니다.'
        req = model(say(ev, ev))
        r = GroundedRag(Guidance(), 'test', request=req).ask('처음인데 뭐부터 하면 돼요?')
        self.assertNotEqual(r['generation_status'], 'generated')
        self.assertIn('후보 검색', r['answer'])
        self.assertNotIn('녹음 파일', r['answer'])

    def test_intake_yes_without_confirmation_process_uses_evidence(self):
        ev = '이 챗봇에서도 대화로 분실 접수와 습득 신고를 할 수 있어요.'
        r = GroundedRag(Guidance(), 'test', request=model(say(ev, ev))).ask('챗봇으로도 분실 접수가 되나요?')
        self.assertIn('접수할게요', r['answer'])
        self.assertNotEqual(r['generation_status'], 'generated')

    def test_number_storage_unknown_is_not_replaced_by_pickup(self):
        def no_model(_):
            self.fail('문서에 없는 보관 방법을 생성하면 안 됨')
        rag = GroundedRag(Guidance(), 'test', request=no_model)
        for q in ('찾기 번호는 어디에 적어 두면 돼요?', '찾기번호 메모는 어느 앱에 해야 해요?',
                  '찾기 번호를 캡처해도 돼요?'):
            r = rag.ask(q)
            self.assertEqual(r['status'], 'policy_pending', q)
            self.assertIn('찾기 번호 보관·메모 방법', r['answer'])
            self.assertNotIn('로봇팔이 물건을 꺼내', r['answer'])
            self.assertFalse(r['generation_used'])

    def test_number_use_and_lost_number_are_not_storage_questions(self):
        g = Guidance()
        for q in ('찾기 번호는 어디에 입력해요?', '찾기 번호를 잊어버렸어요', '찾기 번호 받고 어디로 가요?'):
            self.assertNotEqual(g.ask(q)['status'], 'policy_pending', q)

    def test_optional_contact_requires_unambiguous_wording(self):
        q = '주운 사람 연락처도 남겨야 하나요?'
        for answer in ('연락처는 남기지 않아도 돼요.', '연락처 입력은 선택입니다.',
                       '연락처는 필수가 아닙니다.', '안 남겨도 됩니다.'):
            self.assertTrue(contact_optional_clear(q, answer), answer)
        for answer in ('연락처는 남겨야 하지 않습니다.', '물건을 상자에 놓으세요.', '연락처는 꼭 남겨야 합니다.',
                       '선택이 아니라 필수예요.', '안 남겨도 안 돼요.', '남기지 않아도 안 됩니다.'):
            self.assertFalse(contact_optional_clear(q, answer), answer)
        self.assertTrue(contact_optional_clear('물건 사진은 언제 찍어요?', '손을 빼면 찍어요.'))

    def test_general_pickup_cannot_be_replaced_by_staff_exception(self):
        ev = '직원 보관 선반에 있는 물건은 직원이 가져다 줍니다.'
        rag = GroundedRag(Guidance(), 'test', request=model(say(ev, ev)))
        r = rag.ask('본센터에서 물건은 직원한테 받나요?')
        self.assertNotEqual(r['generation_status'], 'generated')
        self.assertIn('직접', r['answer'])
        self.assertIn('물건 받았어요', r['answer'])

    def test_staff_exception_question_does_not_require_self_pickup(self):
        passages = [{'text': "직접 꺼내고 '물건 받았어요'를 누릅니다. 직원 보관 선반은 직원이 건넵니다."}]
        self.assertEqual(generation_requirements('직원 보관 선반 물건도 직접 받나요?', passages), [])
        self.assertEqual(generation_requirements('본센터에서 직원한테 받나요?',
                                                [{'text': '직원이 확인합니다.'}]), [])

    def test_pickup_timing_accepts_after_removing_item(self):
        q = '물건 받았어요 버튼은 언제 눌러요?'
        self.assertIsNone(answer_gap(q, "물건을 직접 꺼낸 뒤 '물건 받았어요'를 누릅니다."))
        self.assertEqual(answer_gap(q, '키오스크 버튼을 누릅니다.'), 'when')


if __name__ == '__main__':
    unittest.main()
