import unittest
import os
import tempfile
from unittest.mock import patch, AsyncMock
from xml.etree.ElementTree import Element
from fastapi.testclient import TestClient
from src.main import app
from src.core.permissions import CurrentUser, get_current_user
from src.xml_curl.dialplan import add_voicemail_block

class TestE2EVoicemailSystem(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            user_id="u-1", tenant_id="00000000-0000-0000-0000-000000000001",
            username="admin", email="admin@acme.com", role="TENANT_ADMIN"
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("src.xml_curl.dialplan.ensure_voicemail_prompt", return_value="/var/lib/freeswitch/recordings/prompts/voicemail_1001.wav")
    def test_dialplan_voicemail_flow_generation(self, mock_prompt):
        cond = Element("condition")
        add_voicemail_block(cond, "1001", "acme.pbx", "00000000-0000-0000-0000-000000000001")
        actions = cond.findall("action")
        app_names = [a.attrib.get("application") for a in actions]

        self.assertIn("answer", app_names)
        self.assertIn("playback", app_names)
        self.assertIn("record", app_names)
        self.assertIn("hangup", app_names)

        # Confirm 1000Hz beep tone is queued
        beep_actions = [a for a in actions if a.attrib.get("application") == "playback" and "tone_stream" in a.attrib.get("data", "")]
        self.assertTrue(len(beep_actions) > 0)
        self.assertIn("%(500,0,1000)", beep_actions[0].attrib["data"])

    @patch("src.xml_curl.router.execute_query_one")
    @patch("src.xml_curl.router.execute_query")
    @patch("src.xml_curl.router.send_voicemail_notification", new_callable=AsyncMock)
    @patch("src.xml_curl.router.ws_manager.broadcast_voicemail_created", new_callable=AsyncMock)
    def test_voicemail_webhook_pipeline(self, mock_ws, mock_email, mock_exec, mock_exec_one):
        mock_exec_one.side_effect = [
            {"id": "ext-1", "email": "alice@acme.com", "display_name": "Alice", "tenant_name": "Acme Corp"},
            {"id": "box-1"}
        ]

        res = self.client.post("/freeswitch/voicemail", params={
            "extension_number": "1001",
            "caller_id_number": "+15559876543",
            "caller_id_name": "VIP Client",
            "file_path": "/var/lib/freeswitch/recordings/voicemail/1001_abc.wav",
            "duration": "45",
            "tenant_id": "00000000-0000-0000-0000-000000000001"
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["email_sent_to"], "alice@acme.com")
        self.assertTrue(mock_email.called)
        self.assertTrue(mock_ws.called)

    @patch("src.api.v1.reports.execute_query")
    def test_voicemail_reports_endpoint(self, mock_query):
        mock_query.side_effect = [
            # summary query
            [
                {
                    "extension_number": "1001",
                    "display_name": "Alice",
                    "email": "alice@acme.com",
                    "total_messages": 5,
                    "unread_messages": 2,
                    "total_duration_seconds": 180,
                    "latest_message_at": "2026-10-14 12:00:00"
                }
            ],
            # messages list
            [
                {
                    "id": "msg-123",
                    "extension_number": "1001",
                    "display_name": "Alice",
                    "mailbox": "1001",
                    "caller_id_number": "+15559876543",
                    "caller_id_name": "VIP Client",
                    "file_path": "/tmp/test_vm.wav",
                    "duration": 45,
                    "read": False,
                    "created_at": "2026-10-14 12:00:00"
                }
            ]
        ]

        res = self.client.get("/api/v1/reports/voicemail")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_messages"], 5)
        self.assertEqual(data["unread_messages"], 2)
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["id"], "msg-123")

    @patch("src.api.v1.reports.execute_query")
    def test_toggle_voicemail_read(self, mock_query):
        res = self.client.patch("/api/v1/reports/voicemail/00000000-0000-0000-0000-000000000001/read?read=true")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["read"], True)

    @patch("src.api.v1.reports.execute_query_one")
    def test_stream_voicemail_audio(self, mock_query_one):
        # Create a temporary dummy wav file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(b"RIFFdummydataWAVE")
            dummy_path = tf.name

        try:
            mock_query_one.return_value = {"file_path": dummy_path}
            res = self.client.get("/api/v1/reports/voicemail/00000000-0000-0000-0000-000000000001/audio")
            self.assertEqual(res.status_code, 200)
            self.assertIn("audio", res.headers.get("content-type", ""))
        finally:
            if os.path.exists(dummy_path):
                os.remove(dummy_path)

if __name__ == "__main__":
    unittest.main()
