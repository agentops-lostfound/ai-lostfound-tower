import json
from pathlib import Path
import unittest

from agents.guidance import Guidance
from agents.chat_rag import GroundedRag, generation_requirements
from evaluation.chat_eval import Runner, ROOT
from tools.validate_chat_datasets import isolated_env
from unittest import mock


class MissingGuidancePathsTest(unittest.TestCase):
    def test_button_timing_question_retrieves_actual_handover_procedure(self):
        rag = GroundedRag(Guidance())
        for question in ('물건 받았어요 버튼은 언제 눌러요?', '물건 받았어요는 언제 누르나요?'):
            result = rag.ask(question)
            self.assertEqual(result['status'], 'answered')
            self.assertIn('center_pickup', {s['topic'] for s in result['sources']})
            self.assertIn('꺼내', result['answer'])
            self.assertIn('물건 받았어요', result['answer'])

    def test_required_identity_document_before_noun_still_retrieves_preparation(self):
        result = Guidance().ask('받을 때 필요한 신분증도 알려줘')
        self.assertEqual(result['status'], 'answered')
        self.assertIn('pickup', {s['topic'] for s in result['sources']})
        self.assertIn('신분증', result['answer'])

    def test_model_cannot_drop_identity_document_for_inverted_phrase(self):
        required = generation_requirements('받을 때 필요한 신분증도 알려줘',
                                           [{'text': '신분증을 가지고 방문하세요.'}])
        self.assertIn(['신분증'], required)

    def test_original_supplemental_cases_pass_without_changing_expectations(self):
        paths = [('chat_integration_1111_cases.json', 1004), ('chat_guidance_quality_cases.json', 4)]
        with mock.patch.dict('os.environ', isolated_env(), clear=True):
            runner = Runner()
            for name, number in paths:
                items = json.loads((Path(ROOT) / 'evaluation' / name).read_text(encoding='utf-8'))
                item = next(i for i in items if i['no'] == number)
                result = runner.run_item(item)
                self.assertEqual(result['score'], 1, result['why'])

    def test_reward_intent_keeps_contact_private_and_does_not_invent_reward_amount(self):
        rag = GroundedRag(Guidance())
        result = rag.ask('주운 사람한테 사례하고 싶어요')
        self.assertIn('finder_privacy', {s['topic'] for s in result['sources']})
        self.assertIn('연락처', result['answer'])
        self.assertIn('확정', result['answer'])
        self.assertFalse(result['generation_used'])

    def test_reward_money_is_not_confused_with_center_pickup_fee(self):
        result = Guidance().ask('주운 사람한테 사례금 얼마 드려야 해요?')
        self.assertNotIn('fee', {s['topic'] for s in result['sources']})
        self.assertNotIn('무료', result['answer'])
        self.assertIn('확정', result['answer'])

    def test_gratitude_intent_uses_contact_privacy_rule(self):
        result = GroundedRag(Guidance()).ask('주우신 분에게 감사 인사를 전하고 싶어요')
        self.assertIn('finder_privacy', {s['topic'] for s in result['sources']})
        self.assertIn('직원', result['answer'])

    def test_original_live_case_seven_passes_without_changing_expectation(self):
        from tools.chat_live_check import check
        items = json.loads((Path(ROOT) / 'evaluation/chat_live_questions.json').read_text(encoding='utf-8'))
        result = GroundedRag(Guidance()).ask(items[6]['q'])
        self.assertEqual(check(items[6], result), [])
