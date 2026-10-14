import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from src.main import app

class TestVoicemailIngestion(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("src.xml_curl.router.execute_query_one")
    @patch("src.xml_curl.router.execute_query")
    @patch("src.xml_curl.router.send_voicemail_notification", new_callable=AsyncMock)
    @patch("src.xml_curl.router.ws_manager.broadcast_voicemail_created", new_callable=AsyncMock)
    def test_voicemail_webhook_ingestion(self, mock_ws, mock_send_email, mock_exec, mock_exec_one):
        mock_exec_one.side_effect = [
            {"id": "ext-1", "email": "alice@acme.com", "display_name": "Alice", "tenant_name": "Acme"},
            {"id": "box-1"}
        ]

        response = self.client.post("/freeswitch/voicemail", params={
            "extension_number": "1001",
            "caller_id_number": "+15551234567",
            "caller_id_name": "John Doe",
            "file_path": "/var/lib/freeswitch/recordings/voicemail/1001_12345.wav",
            "duration": "24",
            "tenant_id": "00000000-0000-0000-0000-000000000001"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["email_sent_to"], "alice@acme.com")
        self.assertTrue(mock_send_email.called)
        self.assertTrue(mock_ws.called)

        # Check WebSocket event structure passed to broadcast_voicemail_created
        ws_event = mock_ws.call_args[0][0]
        self.assertEqual(ws_event["caller_id_number"], "+15551234567")
        self.assertEqual(ws_event["extension_number"], "1001")

if __name__ == "__main__":
    unittest.main()
