"""Synthetic SQLite view bridges existing search and collection schemas for this test only."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from agents.chatbot import Chatbot
from agents.chat_rag import GroundedRag
from agents.chat_search import DemoItemDatabase, SearchAgent
from agents.guidance import Guidance
from agents.lost_api import create_app
from agents.lost_input import DescriptionService, KST
from agents.center_api import create_app as center_app
from center.demo_collections import DemoCollections


class SllmCollectionWorkflowTests(unittest.TestCase):
    def build_bot(self, guide, database, failure, payloads):
        def generate(payload):
            payloads.append(payload)
            if failure[0]:
                raise TimeoutError('SYNTHETIC_MODEL_FAILURE')
            passages = json.loads(payload['messages'][1]['content'])['retrieved_passages']
            return {'done': True, 'message': {'content': json.dumps({
                'passage_ids': list(range(len(passages)))})}}
        return Chatbot(guide, rag=GroundedRag(guide, 'synthetic-small-model', generate),
                       search=SearchAgent(database))

    def test_confirm_model_search_collection_arrival_statistics_share_synthetic_state(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'synthetic.sqlite3'
            store = DemoCollections(path)
            database = DemoItemDatabase(path)
            # Only this disposable fixture gets a view between the two demo schemas.
            # Running 8110/8111/8112 demos remain separate; this is not production wiring.
            with store.connection(write=True) as db:
                db.execute('DROP TABLE chat_demo_catalog')
                db.execute('''CREATE VIEW chat_demo_catalog AS
                    SELECT item_id,category,color,status,
                        CASE machine_id WHEN 'KIOSK-A' THEN '2호선' ELSE '1호선' END AS line,
                        CASE machine_id WHEN 'KIOSK-A' THEN '해운대'
                            WHEN 'KIOSK-B' THEN '중앙' ELSE '서면' END AS station,
                        date(received_at/1000000,'unixepoch','+9 hours') AS received_date
                    FROM demo_item''')
            guide = Guidance()
            failure = [False]
            payloads = []
            bot = self.build_bot(guide, database, failure, payloads)
            with TestClient(create_app(DescriptionService(), guide, bot), base_url='http://127.0.0.1') as chat, \
                    TestClient(center_app(collections=store, demo=True), base_url='http://127.0.0.1') as center:
                center.headers['x-demo-revision'] = store.dashboard()['revision']
                metadata = {'lost_date': (datetime.now(KST).date()-timedelta(days=1)).isoformat(),
                            'lost_line': '2호선', 'lost_station': '해운대역'}
                proposal = chat.post('/descriptions/text', json={'text': '검정 지갑', **metadata}).json()
                confirmed = chat.post('/descriptions/'+proposal['proposal_id']+'/confirm',
                                      json={'confirmed': True}).json()
                self.assertFalse(confirmed['identity_verified'])
                context = {**metadata, **confirmed['description']}
                def check(expected):
                    response = chat.post('/chat/questions', json={
                        'question': '찾아줘. 수령 절차도 알려줘', 'search_context': context})
                    self.assertEqual(response.status_code, 200, response.text)
                    result = response.json()
                    self.assertEqual(len(result['candidates']), expected)
                    self.assertEqual(result['search_status'], 'items_found' if expected else 'items_not_found')
                    self.assertEqual(result['generation_used'], not failure[0])
                    self.assertTrue(result['sources'])
                    self.assertFalse(result['reservation_created'])
                    self.assertNotIn('A-W01', str(result))
                    self.assertNotIn('SYNTHETIC_MODEL_FAILURE', str(result))
                    stats = center.post('/statistics/questions', json={'question': '오늘 등록기계 A에 들어온 지갑 몇 개?'})
                    self.assertEqual(stats.status_code, 200, stats.text)
                    self.assertEqual(stats.json()['count'], 1)
                check(1)
                pickup = {'machine_id': 'KIOSK-A', 'item_ids': ['A-W01', 'A-W02'], 'request_id': 'sllm-collection-001'}
                response = center.post('/collections', json=pickup)
                self.assertEqual(response.status_code, 200, response.text)
                cid = response.json()['collection_id']
                self.assertEqual(center.post('/collections', json=pickup).json()['collection_id'], cid)
                failure[0] = True
                check(0)  # A failed model cannot bring an item in transit back into search.
                failure[0] = False
                arrivals = f'/collections/{cid}/arrivals'
                self.assertEqual(center.post(arrivals, json={'item_ids': ['A-W02']}).status_code, 200)
                check(0)
                self.assertEqual(len(store.dashboard()['alerts']), 1)
                self.assertEqual(center.post(arrivals, json={'item_ids': ['A-W01']}).status_code, 200)
                self.assertEqual(center.post(arrivals, json={'item_ids': ['A-W01']}).status_code, 200)
                check(1)
                final = store.dashboard()
                self.assertEqual(final['alerts'], [])
                self.assertEqual(final['event_count'], 4)
                self.assertEqual(len(final['collections']), 1)
                self.assertNotIn('A-W01', json.dumps(payloads))


class ModelCollectionWorkflowTests(SllmCollectionWorkflowTests):
    """Run the identical description/search/pickup/arrival flow on the new engine."""
    def build_bot(self, guide, database, failure, payloads):
        from agents.model_chatbot import ModelChatbot
        def generate(payload):
            payloads.append(payload)
            if failure[0]:
                raise TimeoutError('SYNTHETIC_MODEL_FAILURE')
            if 'supported' in payload['format']['properties']:
                value = {'supported': True, 'responsive': True}
            else:
                value = {'answer': '이번 조건의 조회 결과를 확인해주세요. 수령은 본센터에서 확인이 필요해요.',
                         'topics': ['pickup']}
            return {'done': True, 'message': {'content': json.dumps(value)}}
        return ModelChatbot(guide, 'synthetic-selected-model', SearchAgent(database), generate)
