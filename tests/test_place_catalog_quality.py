"""Catalog boundary, privacy and storage failures without any operational DB."""
import unittest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from agents.center_api import create_app
from center.places import Places


class PlaceCatalogQualityTests(unittest.TestCase):
    def client(self, places=None, **kwargs):
        client = TestClient(create_app(places=places, staff_key='synthetic-key', **kwargs))
        self.addCleanup(client.close)
        client.headers['x-staff-key'] = 'synthetic-key'
        return client

    def test_malformed_inputs_are_rejected_before_connecting(self):
        connect = MagicMock(); places = Places(connect)
        for machine in (None, [], {}, '', 'A'*17, 'KIOSK-A\n', '010-1234-5678', 'KIOSK A'):
            with self.subTest(machine=machine), self.assertRaises(ValueError):
                places.recommend(machine)
        for args in [('1호선', '초량', '010-1234-5678'), ('1호선', '초량', '\u200b'),
                     ('0호선', '초량', '승강장'), ('1호선', '역', '승강장')]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                places.put(*args)
        connect.assert_not_called()

    def test_unauthorized_reads_and_writes_do_not_reach_the_store(self):
        store = MagicMock(); client = self.client(store); client.headers.pop('x-staff-key')
        self.assertEqual(client.get('/places?machine_id=KIOSK-A').status_code, 403)
        self.assertEqual(client.post('/places', json={'line': '1호선', 'station': '초량', 'label': '승강장'}).status_code, 403)
        store.recommend.assert_not_called(); store.put.assert_not_called()

    def test_extra_fields_and_invalid_paging_do_not_reach_the_store(self):
        store = MagicMock(); client = self.client(store)
        self.assertEqual(client.post('/places', json={'line': '1호선', 'station': '초량', 'label': '승강장', 'sql': 'SELECT 1'}).status_code, 422)
        for offset in ('true', '1.5', 'not-a-number'):
            self.assertEqual(client.get('/places', params={'machine_id': 'KIOSK-A', 'offset': offset}).status_code, 422)
        store.put.assert_not_called(); store.recommend.assert_not_called()

    def test_storage_failure_is_unavailable_instead_of_a_successful_empty_catalog(self):
        store = MagicMock(); client = self.client(store)
        store.recommend.side_effect = RuntimeError('synthetic-private-connection-string')
        response = client.get('/places?machine_id=KIOSK-A')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('synthetic-private', response.text)
        self.assertNotIn('places', response.json())
        store.put.side_effect = RuntimeError('synthetic-private-connection-string')
        response = client.post('/places', json={'line': '1호선', 'station': '초량', 'label': '승강장'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('같은 내용', response.json()['detail'])
        self.assertNotIn('synthetic-private', response.text)

    def test_missing_configuration_remains_distinct_from_empty_catalog(self):
        response = self.client().get('/places?machine_id=KIOSK-A')
        self.assertEqual(response.status_code, 503)
        self.assertIn('설정', response.json()['detail'])

    def test_validation_response_never_echoes_rejected_body(self):
        response = self.client(MagicMock()).post('/places', json=['synthetic-private-body'])
        self.assertEqual(response.status_code, 422)
        self.assertNotIn('synthetic-private-body', response.text)
