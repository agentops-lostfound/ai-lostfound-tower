import tempfile
import unittest
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
        result = self.client.post('/chat/questions', json={'question': '검정 립밤 찾아줘'}).json()
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
