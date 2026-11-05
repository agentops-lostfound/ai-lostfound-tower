import unittest
from unittest.mock import MagicMock
try:
    from fastapi.testclient import TestClient
    from agents.center_api import create_app
except ImportError:
    TestClient = None


@unittest.skipUnless(TestClient, "fastapi/httpx required")
class CenterApiTests(unittest.TestCase):
    def test_staff_auth_is_required(self):
        client = TestClient(create_app(staff_key="test-key"))
        self.assertEqual(client.get("/collections/1").status_code, 403)
        self.assertEqual(client.get("/collections/1", headers={"x-staff-key": "test-key"}).status_code, 503)
        self.assertEqual(TestClient(create_app(staff_key="")).get("/collections/1").status_code, 503)

    def test_authenticated_request_reaches_store(self):
        store = MagicMock()
        store.pickup.return_value = {"collection_id": 3}
        client = TestClient(create_app(collections=store, staff_key="test-key"))
        response = client.post("/collections", json={"machine_id": "KIOSK-A", "item_ids": ["A-W01"], "request_id": "request001"}, headers={"x-staff-key": "test-key"})
        self.assertEqual(response.json(), {"collection_id": 3})
        store.pickup.assert_called_once_with("KIOSK-A", ["A-W01"], "request001")
