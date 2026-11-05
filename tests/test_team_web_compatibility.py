"""Latest team intake routes and separate LF-5/LF-9 boundaries, no hardware or team DB."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agents.api import build_app
from agents.service import TowerService, demo_backend_factory
from discord_ops.reporter import Reporter
from agents.contracts import ITEM_ID_RE, MACHINE_LETTERS
from agents.center_api import create_app as center_app
from center.demo_collections import DemoCollections
from agents.chatbot import Chatbot
from agents.chat_search import SearchAgent
from agents.guidance import Guidance
from agents.lost_input import DescriptionService
from agents.lost_api import create_app as lost_app
from center.demo_audit import audit_demo


class TeamWebCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.service = TowerService(demo_backend_factory, Reporter(dry_run=True))
        self.client = TestClient(build_app(self.service), base_url='http://127.0.0.1:8100')

    def test_latest_kiosk_intake_lost_and_staff_routes_exist(self):
        for route in ['/kiosk?machine=KIOSK-C', '/intake?machine=KIOSK-A', '/lost', '/staff']:
            with self.subTest(route=route):
                result = self.client.get(route)
                self.assertEqual(result.status_code, 200)
                self.assertIn('text/html', result.headers['content-type'])

    def test_team_c_machine_reception_uses_canonical_receipt_and_does_not_change_local_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo = DemoCollections(Path(tmp) / 'isolated.sqlite3')
            before = demo.dashboard()
            places = self.client.get('/places?machine_id=KIOSK-C').json()
            result = self.client.post('/items', json={'machine_id': 'KIOSK-C', 'place_id': places[0]['place_id'], 'place_text': places[0]['label']})
            self.assertEqual(result.status_code, 200)
            receipt = result.json()
            self.assertRegex(receipt['item_id'], ITEM_ID_RE)
            self.assertTrue(receipt['item_id'].startswith(MACHINE_LETTERS['KIOSK-C']+'-'))
            self.assertIn(receipt['item_id'], self.service.intake.items)
            self.assertFalse(receipt['contact_saved'])
            self.assertEqual(before, demo.dashboard())

    def test_places_response_shapes_are_explicitly_separate(self):
        team_places = self.client.get('/places?machine_id=KIOSK-A').json()
        self.assertIsInstance(team_places, list)
        with tempfile.TemporaryDirectory() as tmp:
            demo = TestClient(center_app(collections=DemoCollections(Path(tmp)/'demo.sqlite3'), demo=True), base_url='http://127.0.0.1:8110')
            manager_places = demo.get('/places?machine_id=KIOSK-A').json()
            self.assertIsInstance(manager_places, dict)
            self.assertIn('next_offset', manager_places)
            self.assertEqual(manager_places['mode'], 'demo_sqlite')
            self.assertEqual(self.client.get('/collection-dashboard').status_code, 404)

    def test_team_claim_record_is_not_a_verified_chat_search_session(self):
        claim = self.client.post('/claims', json={'consent': True, 'name_masked': '시*연', 'id_no_masked': '******',
            'id_verified': True, 'description': {'category': '지갑'}, 'item_id': 'A-W01',
            'quiz': [{'field': 'mark', 'passed': True}], 'visit_date': '2026-11-05'})
        self.assertEqual(claim.status_code, 200)
        database = MagicMock(mode='postgres')
        guide = Guidance()
        chat = TestClient(lost_app(DescriptionService(), guide, Chatbot(guide, search=SearchAgent(database))), base_url='http://127.0.0.1:8111')
        result = chat.post('/chat/questions', headers={'Authorization': 'Bearer '+claim.json()['claim_id']},
                           json={'question': '검정 지갑 찾아줘', 'consent': True, 'id_verified': True})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'authentication_required')
        database.search.assert_not_called()

    def test_legacy_seomyeon_demo_ids_align_without_losing_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'demo.sqlite3'
            demo = DemoCollections(path)
            current = MACHINE_LETTERS['KIOSK-C']+'-W01'
            cid = demo.pickup('KIOSK-C', [current], 'seomyeon-request-001')['collection_id']
            demo.arrive(cid, [])
            old_revision = demo.dashboard()['revision']
            with demo.connection(write=True) as db:
                for table in ('demo_item','demo_member','demo_alert','demo_event'):
                    db.execute('UPDATE '+table+' SET item_id=? WHERE item_id=?', ('C-W01',current))
            updated = DemoCollections(path)
            self.assertNotEqual(updated.dashboard()['revision'], old_revision)
            self.assertEqual(updated.get(cid)['items'][0]['item_id'], current)
            self.assertEqual(updated.dashboard()['event_count'], 1)
            self.assertEqual(updated.dashboard()['alerts'][0]['item_id'], current)
            self.assertEqual(audit_demo(updated)['status'], 'ok')
