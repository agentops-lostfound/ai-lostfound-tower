import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agents.chatbot import Chatbot
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance


class ColorLimitTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = DemoItemDatabase(Path(folder.name)/'demo.sqlite3')
        self.bot = Chatbot(Guidance(), search=SearchAgent(self.database))

    def test_user_reported_fullwidth_multicolor_item_switch_and_pale_purple(self):
        history = []
        first = self.bot.ask('ｕｓｂ잃어버렸어')
        self.assertEqual(first['search_filter']['category'], 'USB')
        history.append('ｕｓｂ잃어버렸어')
        result = self.bot.ask('빨강／검정임', history=history)
        self.assertEqual(result['color_issue'], 'multiple')
        self.assertNotIn('부정', result['answer'])
        self.assertFalse(result['item_search_performed'])
        history.append('빨강／검정임')
        result = self.bot.ask('휴대폰도 같이잃어버렸어', history=history)
        self.assertEqual(result['search_filter']['category'], '모형폰')
        self.assertNotIn('color', result['search_filter'])
        history.append('휴대폰도 같이잃어버렸어')
        with patch.object(self.database, 'search') as query:
            result = self.bot.ask('연보라색이야', history=history)
            self.assertEqual(result['understood_category'], '모형폰')
            self.assertEqual(result['color_issue'], 'unsupported')
            self.assertIn('색상 목록', result['answer'])
            self.assertEqual(result['sources'], [])
            self.assertFalse(result['item_search_performed'])
            query.assert_not_called()

    def test_multicolor_formats_are_not_negation_and_never_silently_choose_one(self):
        with patch.object(self.database, 'search') as query:
            for q in ['빨강/검정임', '빨강+검정', '빨강과 검정', '빨강 또는 검정', '검정, 흰색']:
                result = self.bot.ask(q, history=['USB 잃어버렸어'])
                self.assertEqual(result['color_issue'], 'multiple', q)
                self.assertEqual(result['understood_category'], 'USB')
                self.assertNotIn('부정', result['answer'])
                self.assertFalse(result['item_search_performed'])
            query.assert_not_called()

    def test_unmapped_colors_and_shades_keep_the_item_instead_of_document_routing(self):
        for q in ['연보라색이야', '라벤더색', '민트임', '연회색이야', '베이지', '아이보리색', '보라색이야']:
            result = self.bot.ask(q, history=['휴대폰 잃어버렸다'])
            self.assertEqual(result['color_issue'], 'unsupported', q)
            self.assertEqual(result['understood_category'], '모형폰')
            self.assertFalse(result['item_search_performed'])
            self.assertEqual(result['sources'], [])

    def test_only_explicit_representative_color_confirmation_resumes_search(self):
        history = ['휴대폰 잃어버렸다', '연보라색이야']
        result = self.bot.ask('다시 찾아줘', history=history)
        self.assertFalse(result['item_search_performed'])
        self.assertNotIn('부정', result['answer'])
        result = self.bot.ask('그럼 검정으로', history=history)
        self.assertEqual(result['status'], 'items_found')
        self.assertEqual(result['search_filter']['category'], '모형폰')
        self.assertEqual(result['search_filter']['color'], '검정')

    def test_simultaneous_items_require_selection_and_do_not_share_colors(self):
        result = self.bot.ask('빨강 USB랑 휴대폰 같이 잃어버렸어')
        self.assertEqual(result['status'], 'search_needs_details')
        self.assertFalse(result['item_search_performed'])
        result = self.bot.ask('휴대폰부터', history=['빨강 USB랑 휴대폰 같이 잃어버렸어'])
        self.assertEqual(result['status'], 'items_found')
        self.assertEqual(result['search_filter']['category'], '모형폰')
        self.assertNotIn('color', result['search_filter'])

    def test_accessory_unmapped_color_does_not_replace_main_item_color(self):
        result = self.bot.ask('연보라 케이스야', history=['검정 휴대폰 찾아줘'])
        self.assertFalse(result['item_search_performed'])
        result = self.bot.ask('다시 찾아줘', history=['검정 휴대폰 찾아줘', '연보라 케이스야'])
        self.assertEqual(result['search_filter']['color'], '검정')
