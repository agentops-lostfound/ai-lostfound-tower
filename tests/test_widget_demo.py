import tempfile
import unittest
import json
from unittest.mock import patch
from pathlib import Path
from fastapi.testclient import TestClient
from tools.run_chat_widget_demo import create_app


class WidgetDemoTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.client = TestClient(create_app(Path(tmp.name)/'demo.sqlite3'), base_url='http://127.0.0.1:8112')
        self.addCleanup(self.client.close)

    def test_demo_serves_updated_widget_and_synthetic_chat_without_operational_routes(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('/chat-widget/widget.js', page.text)
        self.assertIn("style-src 'self' 'unsafe-inline';", page.headers['content-security-policy'])
        self.assertIn("script-src 'self';", page.headers['content-security-policy'])
        script = self.client.get('/chat-widget/widget.js')
        self.assertIn('conversationVersion', script.text)
        self.assertIn('retryHistory', script.text)
        self.assertEqual(self.client.get('/chat/health').json()['search_mode'], 'demo_sqlite')
        result = self.client.post('/chat/questions', json={'question': '검정 지갑 찾아줘'}).json()
        self.assertEqual(result['database_mode'], 'demo_sqlite')
        self.assertEqual(result['status'], 'items_found')
        self.assertFalse(result['reservation_created'])
        for route in ['/items', '/claims', '/robot/state', '/collection-dashboard']:
            self.assertEqual(self.client.get(route).status_code, 404)

    def test_demo_keeps_local_host_origin_and_script_restrictions(self):
        self.assertEqual(self.client.get('/chat/health', headers={'Host': 'example.invalid'}).status_code, 400)
        self.assertEqual(self.client.post('/chat/questions', headers={'Origin': 'https://example.invalid'},
            json={'question': '안녕'}).status_code, 403)
        self.assertNotIn('unsafe-inline', self.client.get('/chat/health').headers['content-security-policy'])

    def test_explicit_model_is_called_through_http_and_offline_falls_back(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(
                create_app(Path(folder)/'demo.sqlite3', model='installed-small-model'),
                base_url='http://127.0.0.1:8112') as client:
            self.assertTrue(client.get('/chat/health').json()['rag_model_configured'])
            with patch('agents.chat_rag.ask_local_model', return_value={
                    'message': {'content': json.dumps({'passage_ids': [1]})}}) as model:
                result = client.post('/chat/questions', json={'question': '사진은 어떻게 올려요?'}).json()
                self.assertTrue(result['generation_used'])
                self.assertTrue(result['sources'])
                payload = model.call_args.args[0]
                self.assertEqual(payload['model'], 'installed-small-model')
                self.assertFalse(payload['stream'])
                self.assertEqual(model.call_args.kwargs['timeout'], 20)
            with patch('agents.chat_rag.ask_local_model', side_effect=TimeoutError('private server detail')):
                result = client.post('/chat/questions', json={'question': '사진은 어떻게 올려요?'}).json()
                self.assertFalse(result['generation_used'])
                self.assertTrue(result['sources'])
                self.assertNotIn('private server detail', str(result))
            with patch('agents.chat_rag.ask_local_model') as model:
                policy = client.post('/chat/questions', json={'question': '주말 운영시간은?'}).json()
                self.assertEqual(policy['status'], 'policy_pending')
                search = client.post('/chat/questions', json={'question': '검정 지갑 찾아줘'}).json()
                self.assertEqual(search['status'], 'items_found')
                self.assertEqual(client.post('/chat/questions', json={
                    'question': '010-1234-5678 내 전화번호야'}).status_code, 422)
                model.assert_not_called()
