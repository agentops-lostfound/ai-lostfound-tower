import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from agents.chatbot import Chatbot
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance


class SearchTurnTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = DemoItemDatabase(Path(folder.name)/'demo.sqlite3')
        self.bot = Chatbot(Guidance(), search=SearchAgent(self.database))

    def test_reported_phone_negation_and_keyring_conversation(self):
        first = self.bot.ask('휴대폰 잃어버렸다')
        self.assertEqual(first['status'], 'items_found')
        self.assertEqual(first['candidates'][0]['color'], '검정')
        history = ['휴대폰 잃어버렸다']
        with patch.object(self.database, 'search') as query:
            result = self.bot.ask('검정색 아니다', history=history)
            self.assertEqual(result['status'], 'clarification_needed')
            self.assertTrue(result['color_confirmation_required'])
            self.assertEqual(result['understood_category'], '모형폰')
            history.append('검정색 아니다')
            result = self.bot.ask('원숭이 키링 달렸다', history=history)
            self.assertIn('휴대폰', result['answer'])
            self.assertIn('추가 특징', result['answer'])
            self.assertIn('실제 물건 색상', result['answer'])
            self.assertNotIn('주운 물건', result['answer'])
            self.assertFalse(result['item_search_performed'])
            query.assert_not_called()

    def test_color_correction_after_details_keeps_phone(self):
        result = self.bot.ask('흰색이야', history=['휴대폰 잃어버렸다', '검정색 아니다', '원숭이 키링 달렸다'])
        self.assertEqual(result['status'], 'items_not_found')
        self.assertEqual(result['search_filter']['category'], '모형폰')
        self.assertEqual(result['search_filter']['color'], '흰색')

    def test_unambiguous_not_black_but_white_is_a_positive_correction(self):
        for question in ['검정색 아니고 흰색이야', '검정 말고 흰색', '검정 아닌 흰색 휴대폰']:
            result = self.bot.ask(question, history=['검정 휴대폰 찾아줘'])
            self.assertEqual(result['status'], 'items_not_found', question)
            self.assertEqual(result['search_filter']['color'], '흰색')

    def test_negation_then_retry_does_not_restore_black_or_broaden_search(self):
        with patch.object(self.database, 'search') as query:
            for question in ['검정은 아니야', '흰색과 검정 중 모르겠어', '검정 아닌 건 아니야']:
                result = self.bot.ask(question, history=['검정 휴대폰 찾아줘'])
                self.assertFalse(result['item_search_performed'])
            result = self.bot.ask('다시 찾아줘', history=['검정 휴대폰 찾아줘', '검정색 아니다', '원숭이 키링 달렸다'])
            self.assertTrue(result['color_confirmation_required'])
            self.assertFalse(result['item_search_performed'])
            query.assert_not_called()

    def test_accessory_color_is_not_used_as_item_color(self):
        with patch.object(self.database, 'search') as query:
            result = self.bot.ask('빨간 원숭이 키링이 달렸어', history=['검정 휴대폰 찾아줘'])
            self.assertFalse(result['item_search_performed'])
            self.assertFalse(result['feature_search_supported'])
            self.assertEqual(result['understood_category'], '모형폰')
            query.assert_not_called()
        result = self.bot.ask('다시 찾아줘', history=['검정 휴대폰 찾아줘', '빨간 원숭이 키링이 달렸어'])
        self.assertEqual(result['search_filter']['color'], '검정')
        self.assertEqual(result['search_filter']['category'], '모형폰')
        result = self.bot.ask('휴대폰에 빨간 키링 달렸어 찾아줘')
        self.assertFalse(result['item_search_performed'])

    def test_history_metadata_is_not_dropped_when_color_is_corrected(self):
        result = self.bot.ask('흰색이야', history=[
            '2026-11-01 1호선 중앙역 검정 휴대폰 찾아줘', '원숭이 키링 달렸다'])
        self.assertEqual(result['search_filter']['lost_date'], '2026-11-01')
        self.assertEqual(result['search_filter']['lost_line'], '1호선')
        self.assertEqual(result['search_filter']['lost_station'], '중앙')

    def test_new_guidance_or_found_report_does_not_become_search_detail(self):
        result = self.bot.ask('원숭이 키링 달린 물건 주웠어', history=['휴대폰 잃어버렸다'])
        self.assertIn('found_report', [s['topic'] for s in result['sources']])
        result = self.bot.ask('원숭이 키링 달렸다', history=['휴대폰 잃어버렸다', '수령 절차 알려줘'])
        self.assertIsNone(result['understood_category'])
        self.assertFalse(result['item_search_performed'])
        result = self.bot.ask('검정 휴대폰 검색 방법 알려줘', context={'category': '모형폰'})
        self.assertEqual(result['agent'], 'guidance')
        self.assertFalse(result['item_search_performed'])

    def test_form_context_and_metadata_survive_correction(self):
        result = self.bot.ask('검정 아니고 흰색', context={
            'category': '모형폰', 'color': '검정', 'lost_line': '1호선', 'lost_station': '중앙역', 'lost_date': '2026-11-01'})
        self.assertEqual(result['search_filter']['color'], '흰색')
        self.assertEqual(result['search_filter']['lost_station'], '중앙')
        self.assertEqual(result['search_filter']['lost_date'], '2026-11-01')

    def test_correction_never_grants_real_search_identity(self):
        db = MagicMock(mode='postgres')
        bot = Chatbot(Guidance(), search=SearchAgent(db))
        result = bot.ask('검정 아니고 흰색', history=['휴대폰 잃어버렸다'])
        self.assertEqual(result['status'], 'authentication_required')
        db.search.assert_not_called()
