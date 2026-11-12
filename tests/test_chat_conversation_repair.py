"""사용자 제보 대화 재현: 의도 연속성·우려 질문·도난과 일반 분실 구별."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from agents.chatbot import Chatbot
from agents.chat_intake import IntakeAgent, detect_start
from agents.chat_rag import GroundedRag
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance
from chat_confirmation_helpers import ui_ask
from test_chat_intake import FakeDesk, ID


class ConversationRepairTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.desk = FakeDesk()
        self.guide = Guidance()
        self.bot = Chatbot(self.guide, rag=GroundedRag(self.guide),
            search=SearchAgent(DemoItemDatabase(Path(self.tmp.name) / 'items.sqlite3')),
            intake=IntakeAgent(desk=self.desk))
        self.history = []

    def say(self, q, **kwargs):
        result = self.bot.ask(q, history=self.history[-4:], session_id='repair', **kwargs)
        self.history.append({'q': q, 'a': result['answer'][:300]})
        return result

    def test_privacy_anxiety_not_missing_id(self):
        for q in ('주민등록번호 넣으면 털리는거아님?', '주민번호 유출 안 돼요?', '신분증 입력 안전해?'):
            with self.subTest(q=q):
                r = self.say(q)
                self.assertIn('실제 주민등록번호는 입력하지 마세요', r['answer'])
                self.assertIn('가상', r['answer'])
                self.assertIn('보장할 수는 없어요', r['answer'])
                self.assertEqual({s['topic'] for s in r['sources']}, {'privacy_input', 'masked_identity'})
                self.assertNotIn('신분증이 없으면', r['answer'])
                self.assertFalse(r['item_search_performed'])

    def test_privacy_referent_and_complaint_preserve_subject(self):
        self.say('주민등록번호 넣으면 털리는거아님?')
        self.assertIn('가상', self.say('그거 넣어도 안전해?')['answer'])
        # 불만 자체는 새 분실 접수나 엉뚱한 이용 안내로 바꾸지 않는다.
        self.say('주민번호 유출되는거 아님?')
        r = self.say('챗봇 멍청하노')
        self.assertIn('개인정보 유출이 걱정', r['answer'])
        self.assertNotIn('아래에서 궁금한 것을', r['answer'])

    def test_wallet_found_actual_reported_sequence(self):
        r = self.say('부산역에서 지갑주움')
        self.assertIn('주우셨군요', r['answer'])
        self.assertIn('역무실', r['answer'])
        self.assertNotIn('본센터는 부산역', r['answer'])
        self.assertNotIn('습득 신고하기', r.get('choices', []))
        self.say('지갑주웠다고')
        for q in ('여기서 접수해줘', '접수해달라고 온라인으로'):
            r = self.say(q)
            self.assertIn('역무실', r['answer'])
            self.assertNotIn('어떤 물건', r['answer'])
            self.assertEqual(r.get('status'), 'intake_failed')
        self.assertIsNone(self.bot.intake.active('repair'))
        self.assertEqual(self.desk.calls, [])

    def test_supported_found_followup_starts_found_not_lost(self):
        self.say('초량에서 파란 휴대폰 주움')
        r = self.say('여기서 접수해줘')
        self.assertEqual(r['intake']['kind'], 'found')
        self.assertEqual(r['intake']['asked'], 'place')
        self.assertIn('파랑', r['answer'])
        self.assertEqual(self.desk.calls, [])
        r = self.say('5번 출구 앞')
        self.assertEqual(r['status'], 'intake_confirm')
        # 말로만 확인했다고 해서 저장하지 않는다.
        self.say('접수할게요')
        self.assertEqual(self.desk.calls, [])
        r = ui_ask(self.bot, '접수할게요', session_id='repair')
        self.assertEqual(r['status'], 'intake_done')
        self.assertEqual(self.desk.calls[0][0], 'found')

    def test_generic_registration_needs_role_without_context(self):
        r = self.say('접수해달라고 온라인으로')
        self.assertEqual(r['status'], 'clarification_needed')
        self.assertEqual(r['choices'], ['분실 접수하기', '습득 신고하기'])
        self.assertIsNone(self.bot.intake.active('repair'))

    def test_explicit_new_role_overrides_old_found_context(self):
        self.say('지갑 주움')
        r = self.say('분실 접수하기')
        self.assertEqual(r['intake']['kind'], 'lost')
        self.assertEqual(r['intake']['asked'], 'category')

    def test_latest_role_and_item_take_precedence(self):
        prior = ['초량에서 검정 휴대폰 주움', '중앙에서 파란 립밤 주웠어요']
        r = self.bot.ask('여기서 접수해줘', history=prior, session_id='latest')
        s = self.bot.intake.active('latest')['slots']
        self.assertEqual((s['category'], s['color'], s['station']), ('립밤', '파랑', '중앙'))
        self.assertEqual(r['intake']['kind'], 'found')

    def test_cancel_and_role_switch_stop_context_carryover(self):
        for prior in (['지갑 주움', '취소'], ['지갑 주움', '휴대폰 잃어버렸어요']):
            with self.subTest(prior=prior):
                kind = detect_start('여기서 접수해줘', prior)
                self.assertEqual(kind, 'clarify' if prior[-1] == '취소' else 'lost')

    def test_unsupported_item_in_history_does_not_restart_empty_form(self):
        self.say('초량에서 우산 주웠어요')
        r = self.say('여기서 신고해줘')
        self.assertEqual(r['status'], 'intake_failed')
        self.assertIn('우산', r['answer'])
        self.assertIn('역무실', r['answer'])

    def test_privacy_interrupt_does_not_consume_or_modify_draft(self):
        for q in ('분실 접수하기', '휴대폰', '파랑', '초량', '오늘', '없어요'):
            self.say(q)
        before = copy.deepcopy(self.bot.intake.active('repair'))
        r = self.say('주민등록번호 넣으면 털리는거아님?')
        self.assertIn('가상', r['answer'])
        self.assertEqual(before, self.bot.intake.active('repair'))
        r = self.say('본인 확인 정보를 입력했어요', intake_action=ID)
        self.assertEqual(r['status'], 'intake_confirm')
        self.assertEqual(self.desk.calls, [])

    def test_theft_is_not_ordinary_loss_even_during_intake(self):
        self.say('분실 접수하기')
        before = copy.deepcopy(self.bot.intake.active('repair'))
        for q in ('물건을뺏겼어요', '휴대폰을 빼앗겼어요', '누가 지갑을 훔쳐갔어요', '휴대폰 도난 신고해줘'):
            r = self.say(q)
            self.assertIn('안전한 곳', r['answer'])
            self.assertIn('도난 신고를 접수할 수 없어요', r['answer'])
            self.assertNotIn('로봇팔', r['answer'])
            self.assertEqual(before, self.bot.intake.active('repair'))
        self.assertEqual(self.desk.calls, [])

    def test_model_cannot_override_critical_interpretation(self):
        self.bot.brain = Mock()
        self.bot.brain.coordinate.side_effect = AssertionError('critical intent reached model')
        for q in ('주민번호 유출 안 돼?', '물건을뺏겼어요', '초량에서 지갑주움'):
            self.say(q)
        self.bot.brain.coordinate.assert_not_called()

    def test_unknown_short_input_does_not_repeat_menu(self):
        for q in ('앙기모띠', '오이쉬', '끼약'):
            r = self.say(q)
            self.assertEqual(r['status'], 'not_found')
            self.assertFalse(r.get('choices'))
            self.assertNotIn('아래에서 궁금한 것을', r['answer'])

    def test_http_history_keeps_found_intent(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from agents.chat_api import add_chat_routes
        app = FastAPI()
        add_chat_routes(app, chatbot=self.bot)
        with TestClient(app, base_url='http://127.0.0.1') as client:
            first = client.post('/chat/questions', json={'question': '초량에서 파란 휴대폰 주움', 'session_id': 'http-repair'})
            self.assertEqual(first.status_code, 200)
            second = client.post('/chat/questions', json={'question': '접수해달라고 온라인으로', 'session_id': 'http-repair',
                'history': [{'q': '초량에서 파란 휴대폰 주움', 'a': first.json()['answer'][:300]}]})
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()['intake']['kind'], 'found')
            self.assertEqual(second.json()['intake']['asked'], 'place')


if __name__ == '__main__':
    unittest.main()
