"""Synthetic media -> review -> HTTP chat/search, with explicit model doubles."""
import base64
import io
import sqlite3
import tempfile
import unittest
import wave
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from PIL import Image
from agents.chatbot import Chatbot
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance
from agents.lost_api import create_app
from agents.lost_input import DescriptionService, KST


class VirtualWorkflowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'synthetic.db'
        self.worker = MagicMock()
        self.worker.__enter__.return_value = self.worker
        self.worker.transcribe.return_value = {'status': 'transcribed', 'text': '검정 지갑'}
        self.photo = MagicMock(return_value={'category': '지갑', 'color': '검정'})
        self.service = DescriptionService(photo_extractor=self.photo, transcriber=lambda: self.worker)
        self.guide = Guidance()
        self.database = DemoItemDatabase(self.path)
        self.bot = Chatbot(self.guide, search=SearchAgent(self.database))
        self.client = TestClient(create_app(self.service, self.guide, self.bot), base_url='http://127.0.0.1:8111')
        self.addCleanup(self.client.close)
        self.metadata = {'lost_date': (datetime.now(KST).date()-timedelta(days=2)).isoformat(),
                         'lost_line': '2호선', 'lost_station': '해운대역'}

    def confirm(self, client, path, payload):
        response = client.post('/descriptions/'+path, json={**self.metadata, **payload})
        self.assertEqual(response.status_code, 200, response.text)
        proposal = response.json()
        url = '/descriptions/'+proposal['proposal_id']+'/confirm'
        self.assertEqual(client.post(url, json={'confirmed': False}).status_code, 422)
        response = client.post(url, json={'confirmed': True})
        self.assertEqual(response.status_code, 200, response.text)
        confirmed = response.json()
        self.assertEqual(confirmed['status'], 'ready_for_search')
        self.assertFalse(confirmed['identity_verified'])
        context = {k: confirmed[k] for k in ('lost_date', 'lost_line', 'lost_station')}
        context.update({k: confirmed['description'][k] for k in ('category', 'color')})
        return context

    def test_text_synthetic_photo_and_audio_share_confirmed_search_handoff(self):
        image = io.BytesIO(); Image.new('RGB', (8, 8), 'white').save(image, format='PNG')
        audio = io.BytesIO()
        with wave.open(audio, 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
            output.writeframes(b'\0\0'*1600)
        cases = [('text', {'text': '검정 지갑'}),
                 ('photo', {'photo': 'data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()}),
                 ('audio', {'audio_base64': base64.b64encode(audio.getvalue()).decode()})]
        for path, payload in cases:
            with self.subTest(source=path):
                context = self.confirm(self.client, path, payload)
                response = self.client.post('/chat/questions', json={'question': '찾아줘', 'search_context': context})
                self.assertEqual(response.status_code, 200, response.text)
                result = response.json()
                self.assertEqual(result['database_mode'], 'demo_sqlite')
                self.assertEqual(result['status'], 'items_found')
                self.assertTrue(result['candidates'])
                self.assertFalse(result['reservation_created'])
                for row in result['candidates']:
                    self.assertEqual(set(row), {'candidate_no', 'category', 'color'})
                self.assertNotIn('DEMO-001', str(result))
        self.photo.assert_called_once()
        self.worker.__exit__.assert_called_once()

    def test_description_confirmation_does_not_grant_real_search_identity(self):
        database = MagicMock(mode='postgres')
        bot = Chatbot(self.guide, search=SearchAgent(database))
        with TestClient(create_app(self.service, self.guide, bot), base_url='http://127.0.0.1') as client:
            context = self.confirm(client, 'text', {'text': '검정 지갑'})
            response = client.post('/chat/questions', json={'question': '찾아줘', 'search_context': context,
                'id_verified': True, 'consent': True}, headers={'Authorization': 'Bearer synthetic-unverified'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'authentication_required')
        database.search.assert_not_called()

    def test_guidance_and_rejected_private_input_do_not_change_demo_inventory(self):
        def rows():
            with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)) as db:
                return db.execute('SELECT * FROM chat_demo_catalog ORDER BY item_id').fetchall()
        before = rows()
        response = self.client.post('/chat/questions', json={'question': '수령 절차와 주말 운영시간 알려줘'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'answered')          # 11/6 시연 운영 기준(운영시간)
        self.assertIn('시연 기준', response.json()['answer'])
        self.assertTrue(response.json()['sources'])
        self.assertEqual(self.client.post('/descriptions/text', json={**self.metadata,
            'text': '검정 지갑 010-1234-5678'}).status_code, 422)
        self.assertEqual(rows(), before)
