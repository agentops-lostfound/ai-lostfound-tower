import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agents.chatbot import Chatbot
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance
from agents.chat_communication import communication_response


class DialogueTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.database = DemoItemDatabase(Path(folder.name)/'synthetic.sqlite3')
        self.bot = Chatbot(Guidance(), search=SearchAgent(self.database))

    def test_user_reported_unknown_item_abuse_repetition_and_scope_confirmation(self):
        history = []
        questions = ['얼박사 잃어버림', 'cu에서 산 얼박사 잃어버렸다고', '시발년아',
                     '아', '아', '아', '아', '오늘날씨', '그래?']
        replies = []
        with patch.object(self.database, 'search') as query:
            for q in questions:
                result = self.bot.ask(q, history=history[-4:])
                self.assertNotIn('반가워', result['answer'], q)
                self.assertFalse(result['item_search_performed'], q)
                replies.append(result)
                history.append(q)
            query.assert_not_called()
        self.assertEqual(replies[0]['status'], 'clarification_needed')
        self.assertIn('어떤 품목', replies[0]['answer'])
        self.assertEqual(replies[1]['status'], 'unsupported')
        self.assertIn('구매처', replies[1]['answer'])
        self.assertIn('답답', replies[2]['answer'])
        self.assertEqual(replies[4]['answer'], '네.')
        self.assertIn('분실물 찾기', replies[-1]['answer'])

    def test_product_name_does_not_prevent_later_explicit_supported_category(self):
        # A complete explicit search still works after a failed unknown-name attempt.
        result = self.bot.ask('흰색 보조배터리 찾아줘', history=['얼박사 잃어버림'])
        self.assertEqual(result['status'], 'items_found')
        self.assertEqual(result['search_filter']['category'], '보조배터리')

    def test_frustration_does_not_swallow_a_supported_search(self):
        result = self.bot.ask('시발 흰색 보조배터리 찾아줘')
        self.assertEqual(result['status'], 'items_found')
        self.assertTrue(result['item_search_performed'])
        result = self.bot.ask('답답한데 사진은 어떻게 올려요?')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['sources'][0]['topic'], 'site_help')

    def test_unknown_loss_does_not_override_known_input_help(self):
        result = self.bot.ask('잃어버렸는데 사진은 어떻게 올려요?')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['sources'][0]['topic'], 'site_help')

    def test_model_cannot_label_arbitrary_text_as_a_greeting(self):
        for q in ['아', '시발년아', '얼박사', '그래?']:
            result = communication_response(Guidance(), 'greeting', q)
            self.assertEqual(result['status'], 'clarification_needed')
            self.assertNotIn('반가워', result['answer'])
