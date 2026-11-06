import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from center.demo_collections import DemoCollections
from center.demo_places import DemoPlaces
from agents.center_api import create_app


class DemoPlaceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DemoCollections(Path(tmp.name) / 'demo.sqlite3')
        self.places = DemoPlaces(self.store)

    def test_recommendations_are_station_scoped_and_page_five_at_a_time(self):
        first = self.places.recommend('KIOSK-A')
        self.assertEqual((len(first['places']), first['next_offset'], first['total']), (5, 5, 6))
        second = self.places.recommend('KIOSK-A', first['next_offset'])
        self.assertEqual((len(second['places']), second['next_offset']), (1, None))
        self.assertTrue(all(p['station'] == '해운대' for p in first['places']))
        self.assertEqual(self.places.recommend('KIOSK-C')['station'], '서면')

    def test_duplicate_normalization_concurrency_and_correct_page(self):
        def add(_):
            return self.places.put('2호선', '해운대역', ' 가상 새 장소 ')
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(add, range(2)))
        self.assertEqual(results[0]['place_id'], results[1]['place_id'])
        self.assertEqual(sum(r['created'] for r in results), 1)
        self.assertIn('가상 새 장소', [p['label'] for p in self.places.recommend('KIOSK-A', results[0]['page_offset'])['places']])

    def test_invalid_scope_private_data_and_paging_are_rejected(self):
        for args in [('2호선', '서면역', '가상 장소'), ('2호선', '해운대', '010-1234-5678'), ('2호선', '해운대', '가' * 65)]:
            with self.assertRaises(ValueError):
                self.places.put(*args)
        for offset in [-1, True, 10001]:
            with self.assertRaises(ValueError):
                self.places.recommend('KIOSK-A', offset)

    def test_api_revision_and_reset_clear_only_synthetic_catalog(self):
        client = TestClient(create_app(collections=self.store, demo=True), base_url='http://127.0.0.1:8110')
        payload = {'line': '2호선', 'station': '해운대역', 'label': '가상 추가 장소'}
        self.assertEqual(client.post('/places', json=payload).status_code, 409)
        client.headers['x-demo-revision'] = self.store.dashboard()['revision']
        self.assertEqual(client.post('/places', json=payload).status_code, 200)
        self.assertEqual(client.get('/places?machine_id=KIOSK-A').json()['total'], 7)
        self.store.reset()
        self.assertEqual(client.post('/places', json=payload).status_code, 409)
        self.assertEqual(self.places.recommend('KIOSK-A')['total'], 6)

    def test_reopening_preserves_places_and_parameterized_label_cannot_write_sql(self):
        label = "가상 장소'; DROP TABLE demo_item;--"
        self.places.put('2호선', '해운대', label)
        self.assertEqual(DemoPlaces(DemoCollections(self.store.path)).recommend('KIOSK-A')['total'], 7)
        self.assertEqual(len(self.store.dashboard()['items']), 6)
