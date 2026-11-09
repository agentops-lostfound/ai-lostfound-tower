import tempfile
import unittest
from pathlib import Path
from agents.chatbot import Chatbot
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance
from agents.lost_input import text_features


class NaturalItemTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.bot = Chatbot(Guidance(), search=SearchAgent(DemoItemDatabase(Path(folder.name)/'demo.sqlite3')))

    def test_reported_three_turn_conversation(self):
        history = []
        for question in ['반갑다', '녹색 반지갑', '녹색 반지갑 찾아']:
            result = self.bot.ask(question, history=history)
            if question == '반갑다':
                self.assertEqual(result['status'], 'answered')
                self.assertFalse(result['item_search_performed'])
            else:
                self.assertEqual(result['status'], 'items_not_found')
                self.assertEqual(result['search_filter']['category'], '지갑')
                self.assertEqual(result['search_filter']['color'], '초록')
                self.assertEqual(result['candidates'], [])
                self.assertIn('색상: 초록', result['answer'])
            history.append(question)

    def test_color_synonyms_keep_search_constraints(self):
        for color, expected in [('녹색', '초록'), ('그린', '초록'), ('green', '초록'),
                                ('적색', '빨강'), ('청색', '파랑'), ('황색', '노랑')]:
            with self.subTest(color=color):
                result = self.bot.ask(color+' 반지갑 찾아줘')
                self.assertEqual(result['search_filter']['color'], expected)
                self.assertEqual(result['candidates'], [])

    def test_short_descriptions_search_without_imperative(self):
        for question in ['검정 지갑', '검은색 반지갑', '회색 USB', '흰색 핸드크림', '검정 지갑이요']:
            with self.subTest(question=question):
                result = self.bot.ask(question)
                self.assertEqual(result['agent'], 'search')
                self.assertEqual(result['status'], 'items_found')
        self.assertEqual(self.bot.ask('지갑 사용 방법 알려줘')['agent'], 'guidance')

    def test_unmapped_color_is_not_silently_ignored(self):
        for question in ['보라색 지갑 찾아줘', '민트색 지갑 찾아줘', '초록색과 보라색 지갑 찾아줘']:
            with self.subTest(question=question):
                result = self.bot.ask(question)
                self.assertEqual(result['status'], 'search_needs_details')
                self.assertFalse(result['item_search_performed'])
                self.assertEqual(result['candidates'], [])

    def test_greeting_variants_and_green_review_input(self):
        for question in ['반가워', '반가워요', '반갑습니다!', '안녕하세요']:
            self.assertEqual(self.bot.ask(question)['status'], 'answered')
        features, warnings = text_features('녹색 반지갑')
        self.assertEqual(features['color'], '초록')
        self.assertEqual(features['shape'], '반지갑')
        self.assertEqual(warnings, [])

    def test_search_word_is_not_misread_as_color(self):
        for question in ['검정 지갑 검색해줘', '지갑 검색', '후보 검색해줘']:
            features, warnings = text_features(question)
            self.assertEqual(warnings, [], question)
