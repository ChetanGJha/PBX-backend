import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from src.main import app
from src.core.permissions import CurrentUser, get_current_user

class TestAudioPrompts(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id="u-1", tenant_id=None, username="admin", email="admin@pbx.local", role="SUPER_ADMIN"
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("src.api.v1.audio.execute_query")
    def test_list_audio_files(self, mock_query):
        mock_query.return_value = [
            {"id": "a-1", "name": "Greeting 1", "file_name": "greet1.wav", "category": "ivr_greeting"}
        ]
        res = self.client.get("/api/v1/audio")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Greeting 1")

    @patch("src.api.v1.audio.execute_query_one")
    def test_stream_audio_not_found(self, mock_query_one):
        mock_query_one.return_value = None
        res = self.client.get("/api/v1/audio/missing-id/stream")
        self.assertEqual(res.status_code, 404)

if __name__ == "__main__":
    unittest.main()
