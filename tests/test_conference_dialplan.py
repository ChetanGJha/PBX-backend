# tests/test_conference_dialplan.py
import unittest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

class TestConferenceDialplan(unittest.IsolatedAsyncioTestCase):
    async def test_conference_dialplan_pin_prompt(self):
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "3000",
            "Caller-Caller-ID-Number": "1001",
            "domain": "pbx.aikyamlabs.local",
            "variable_tenant_id": "tid-1"
        }
        mock_conf = {
            "id": "conf-uuid",
            "name": "Team_Standup",
            "extension_number": "3000",
            "pin": "1234",
            "moderator_pin": "9999",
            "record_conference": True,
            "tenant_id": "tid-1"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from conferences" in q:
                return mock_conf
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn("play_and_get_digits", xml_res)
            self.assertIn("conf_exec_3000_${entered_conf_pin}", xml_res)

    async def test_conference_moderator_pin_entry(self):
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "conf_exec_3000_9999",
            "Caller-Caller-ID-Number": "1001",
            "domain": "pbx.aikyamlabs.local",
            "variable_tenant_id": "tid-1"
        }
        mock_conf = {
            "id": "conf-uuid",
            "name": "Team_Standup",
            "extension_number": "3000",
            "pin": "1234",
            "moderator_pin": "9999",
            "record_conference": True,
            "tenant_id": "tid-1"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from conferences" in q:
                return mock_conf
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('application="conference"', xml_res)
            self.assertIn("+flags{moderator}", xml_res)

    async def test_conference_participant_pin_entry(self):
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "conf_exec_3000_1234",
            "Caller-Caller-ID-Number": "1001",
            "domain": "pbx.aikyamlabs.local",
            "variable_tenant_id": "tid-1"
        }
        mock_conf = {
            "id": "conf-uuid",
            "name": "Team_Standup",
            "extension_number": "3000",
            "pin": "1234",
            "moderator_pin": "9999",
            "record_conference": False,
            "tenant_id": "tid-1"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from conferences" in q:
                return mock_conf
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('application="conference"', xml_res)
            self.assertNotIn("+flags{moderator}", xml_res)

if __name__ == "__main__":
    unittest.main()
