"""문장/위젯 시험과 별도로 전체 HTTP 대화의 상태·업무 쓰기를 검사한다."""
import os
import tempfile
import unittest
from unittest.mock import patch
from evaluation.conversation_quality import run_case
from evaluation.conversation_quality_cases import cases
from evaluation.conversation_quality_holdout import cases as holdout
from evaluation.conversation_quality_quiz import cases as quiz


class ConversationJourneyTest(unittest.TestCase):
    def test_development_and_additional_journeys(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LF_', 'TOWER_', 'LANGFUSE_', 'DISCORD_'))
               and k != 'DATABASE_URL'}
        env.update(LF_LANGFUSE='0', LF_CHAT_RAG_MODEL='', LF_CHAT_AGENT_MODEL='')
        with patch.dict(os.environ, env, clear=True), tempfile.TemporaryDirectory() as tmp:
            for case in cases()+holdout()+quiz():
                with self.subTest(journey=case['id'], group=case['group']):
                    result = run_case(case, tmp)
                    failures = [(t['say'], t['why']) for t in result['turns'] if t['why']]
                    self.assertTrue(result['ok'], failures)

    def test_invalid_setup_fails_instead_of_counting_empty_state_as_preserved(self):
        # 평가 준비 실패를 제품 실패/성공으로 집계하지 않는다.
        case = {'id': 'invalid-fixture', 'group': 'harness', 'setup': ['안녕하세요'], 'turns': []}
        env = {k: v for k, v in os.environ.items() if not k.startswith(('LF_', 'TOWER_', 'LANGFUSE_', 'DISCORD_'))
               and k != 'DATABASE_URL'}
        with patch.dict(os.environ, env, clear=True), tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, '여정 준비 실패'):
                run_case(case, tmp)
