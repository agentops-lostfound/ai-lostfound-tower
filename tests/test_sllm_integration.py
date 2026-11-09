"""Model failure/concurrency must not break search, identity boundaries or API privacy."""
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agents.chatbot import Chatbot
from agents.chat_rag import GroundedRag
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance
from agents.lost_api import create_app
from agents.lost_input import DescriptionService


class SllmIntegrationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.guide = Guidance()
        self.database = DemoItemDatabase(Path(folder.name)/'synthetic.sqlite3')
        self.payloads = []

    def generate(self, payload):
        self.payloads.append(payload)
        passages = json.loads(payload['messages'][1]['content'])['retrieved_passages']
        return {'done': True, 'message': {'content': json.dumps({
            'passage_ids': list(range(len(passages)))})}}

    def bot(self, request=None, search=None):
        return Chatbot(self.guide, rag=GroundedRag(self.guide, 'synthetic-small-model', request or self.generate),
                       search=search or SearchAgent(self.database))

    def test_combined_answer_retains_model_and_component_outcomes(self):
        result = self.bot().ask('검정 지갑 찾아줘. 수령 절차도 알려줘')
        self.assertEqual(result['agent'], 'both')
        self.assertEqual(result['guidance_status'], 'answered')
        self.assertEqual(result['search_status'], 'items_found')
        self.assertEqual(result['generation_status'], 'generated')
        self.assertEqual(result['model'], 'synthetic-small-model')
        self.assertTrue(result['generation_used'])
        self.assertTrue(result['candidates'])
        self.assertTrue(result['sources'])
        self.assertFalse(result['reservation_created'])
        self.assertNotIn('DEMO-001', json.dumps(self.payloads))

    def test_model_failure_keeps_candidates_and_explains_fallback(self):
        request = MagicMock(side_effect=TimeoutError('SYNTHETIC_MODEL_SECRET'))
        result = self.bot(request).ask('검정 지갑 찾아줘. 수령 절차도 알려줘')
        self.assertEqual(result['search_status'], 'items_found')
        self.assertEqual(result['generation_status'], 'unavailable_or_invalid_excerpt_fallback')
        self.assertFalse(result['generation_used'])
        self.assertTrue(result['sources'])
        self.assertTrue(result['candidates'])
        self.assertNotIn('SYNTHETIC_MODEL_SECRET', str(result))

    def test_combined_guidance_never_grants_real_database_access(self):
        database = MagicMock(mode='postgres')
        result = self.bot(search=SearchAgent(database)).ask(
            '검정 지갑 찾아줘. 수령 절차도 알려줘', access_token='SYNTHETIC_PRIVATE_BEARER')
        self.assertEqual(result['search_status'], 'authentication_required')
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['item_search_performed'])
        self.assertTrue(result['generation_used'])
        database.search.assert_not_called()
        self.assertNotIn('SYNTHETIC_PRIVATE_BEARER', json.dumps(self.payloads))

    def test_incomplete_model_reply_uses_document_fallback(self):
        def incomplete(payload):
            return {**self.generate(payload), 'done': False}
        result = self.bot(incomplete).ask('물건 수령 절차 알려줘')
        self.assertFalse(result['generation_used'])
        self.assertEqual(result['generation_status'], 'unavailable_or_invalid_excerpt_fallback')
        self.assertTrue(result['sources'])

    def test_description_chat_api_does_not_expose_internal_failure(self):
        bot = self.bot()
        bot.ask = MagicMock(side_effect=RuntimeError('SYNTHETIC_INTERNAL_SECRET'))
        with TestClient(create_app(DescriptionService(), self.guide, bot),
                        base_url='http://127.0.0.1') as client:
            response = client.post('/chat/questions', json={'question': '수령 절차 알려줘'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('SYNTHETIC_INTERNAL_SECRET', response.text)

    def test_busy_model_does_not_block_another_guidance_or_database_search(self):
        entered, release = threading.Event(), threading.Event()
        def slow(payload):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('test model wait')
            return self.generate(payload)
        bot = self.bot(slow)
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(bot.ask, '물건 수령 절차 알려줘')
            try:
                self.assertTrue(entered.wait(3))
                second = bot.ask('사진은 어떻게 올려요?')
                self.assertEqual(second['generation_status'], 'busy_excerpt_fallback')
                self.assertTrue(second['sources'])
                search = bot.ask('검정 지갑 찾아줘')
                self.assertEqual(search['status'], 'items_found')
                self.assertFalse(search['reservation_created'])
            finally:
                release.set()
            self.assertTrue(first.result(timeout=3)['generation_used'])
