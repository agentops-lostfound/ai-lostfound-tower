import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agents.chatbot import Chatbot
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance


class ChatReactionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = DemoItemDatabase(Path(folder.name)/'demo.sqlite3')
        self.bot = Chatbot(Guidance(), search=SearchAgent(self.database))

    def test_disappointment_is_not_a_new_greeting_or_search(self):
        first = self.bot.ask('노란색 보조배터리')
        self.assertEqual(first['status'], 'items_not_found')
        with patch.object(self.database, 'search', wraps=self.database.search) as query:
            for text in ['까비 ㅋ', '아쉽네 ㅠ', '아깝다ㅋㅋ', '쩝', '에휴']:
                with self.subTest(text=text):
                    result = self.bot.ask(text, history=['노란색 보조배터리'])
                    self.assertEqual(result['status'], 'answered')
                    self.assertIn('아쉽네요', result['answer'])
                    self.assertNotIn('반가워', result['answer'])
                    self.assertFalse(result['item_search_performed'])
                    self.assertNotIn('search_filter', result)
            query.assert_not_called()

    def test_followup_after_reaction_keeps_original_item(self):
        result = self.bot.ask('그럼 흰색은?', history=['노란색 보조배터리', '까비 ㅋ'])
        self.assertEqual(result['status'], 'items_found')
        self.assertEqual(result['search_filter']['category'], '보조배터리')
        self.assertEqual(result['search_filter']['color'], '흰색')

    def test_reaction_does_not_hide_a_new_request_or_invent_previous_result(self):
        result = self.bot.ask('까비 ㅋ')
        self.assertIn('아쉽네요', result['answer'])
        self.assertNotIn('후보가 없', result['answer'])
        self.assertFalse(result['context_used'])
        result = self.bot.ask('아쉽네. 흰색 보조배터리 찾아줘', history=['노란색 보조배터리'])
        self.assertTrue(result['item_search_performed'])
        self.assertEqual(result['search_filter']['color'], '흰색')

    def test_acknowledgement_preserves_search_but_not_after_topic_change(self):
        result = self.bot.ask('오케이', history=['노란색 보조배터리'])
        self.assertFalse(result['item_search_performed'])
        result = self.bot.ask('그럼 흰색은?', history=['노란색 보조배터리', '오케이'])
        self.assertEqual(result['search_filter']['category'], '보조배터리')
        result = self.bot.ask('그럼 흰색은?', history=['노란색 보조배터리', '수령 절차 알려줘', '까비'])
        self.assertFalse(result['item_search_performed'])
