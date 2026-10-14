import unittest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

class TestEndToEndSubProject1(unittest.IsolatedAsyncioTestCase):

    async def test_e2e_internal_calling_toggle_enforcement(self):
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "1002",
            "Caller-Caller-ID-Number": "1001",
            "variable_tenant_id": "11111111-1111-1111-1111-111111111111",
            "domain": "pbx.test.local"
        }
        mock_ext = {
            "id": "ext-1002",
            "extension_number": "1002",
            "display_name": "Bob",
            "caller_id_name": "Bob",
            "caller_id_number": "1002",
            "email": "bob@test.com",
            "enabled": True,
            "no_answer_timeout": 20,
            "sip_domain": "pbx.test.local"
        }

        # Subtest A: Internal calling ENABLED
        mock_tenant_enabled = {"id": "11111111-1111-1111-1111-111111111111", "allow_internal_calls": True, "sip_domain": "pbx.test.local"}
        async def mock_db_enabled(query, params=None):
            q = query.lower()
            if "from extensions" in q:
                return mock_ext
            if "from tenants" in q:
                return mock_tenant_enabled
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db_enabled):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('user/1002@pbx.test.local', xml_res)
            self.assertNotIn("403 Forbidden", xml_res)

        # Subtest B: Internal calling DISABLED
        mock_tenant_disabled = {"id": "11111111-1111-1111-1111-111111111111", "allow_internal_calls": False, "sip_domain": "pbx.test.local"}
        async def mock_db_disabled(query, params=None):
            q = query.lower()
            if "from extensions" in q:
                return mock_ext
            if "from tenants" in q:
                return mock_tenant_disabled
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db_disabled):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('application="respond"', xml_res)
            self.assertIn("403 Forbidden - Internal Calling Disabled", xml_res)
            self.assertIn('data="CALL_REJECTED"', xml_res)
            self.assertNotIn('data="user/1002@pbx.test.local"', xml_res)

    async def test_e2e_inbound_did_destinations(self):
        # 1. Route to Queue
        async def mock_db_queue(query, params=None):
            q = query.lower()
            if "from call_routes" in q or "from dids" in q:
                return {
                    "destination_type": "queue",
                    "destination": "support@default",
                    "tenant_id": "tid-e2e",
                    "sip_domain": "pbx.test.local"
                }
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db_queue):
            xml_q = await handle_dialplan_request({
                "Caller-Context": "public",
                "Caller-Destination-Number": "18005550100"
            })
            self.assertIn('application="callcenter"', xml_q)
            self.assertIn('data="support@default"', xml_q)

        # 2. Route to Hunt Group
        async def mock_db_hg(query, params=None):
            q = query.lower()
            if "from call_routes" in q or "from dids" in q:
                return {
                    "destination_type": "hunt_group",
                    "destination": "8888",
                    "tenant_id": "tid-e2e",
                    "sip_domain": "pbx.test.local"
                }
            if "from hunt_groups" in q:
                return {
                    "extension_number": "8888",
                    "members": "1001, 1002, 1003",
                    "timeout": 30,
                    "tenant_id": "tid-e2e"
                }
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db_hg):
            xml_hg = await handle_dialplan_request({
                "Caller-Context": "public",
                "Caller-Destination-Number": "18005550200"
            })
            self.assertIn('application="bridge"', xml_hg)
            self.assertIn("user/1001@pbx.test.local,user/1002@pbx.test.local,user/1003@pbx.test.local", xml_hg)

        # 3. Route to Conference
        async def mock_db_conf(query, params=None):
            q = query.lower()
            if "from call_routes" in q or "from dids" in q:
                return {
                    "destination_type": "conference",
                    "destination": "3000",
                    "tenant_id": "tid-e2e",
                    "sip_domain": "pbx.test.local"
                }
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db_conf):
            xml_conf = await handle_dialplan_request({
                "Caller-Context": "public",
                "Caller-Destination-Number": "18005550300"
            })
            self.assertIn('application="transfer"', xml_conf)
            self.assertIn('data="3000 XML public"', xml_conf)

    async def test_e2e_conference_dialplan_pins(self):
        mock_conf = {
            "id": "conf-uuid-e2e",
            "name": "Executive Room",
            "extension_number": "3500",
            "pin": "1234",
            "moderator_pin": "9999",
            "record_conference": True,
            "tenant_id": "tid-e2e"
        }

        async def mock_db_conf_only(query, params=None):
            q = query.lower()
            if "from conferences" in q:
                return mock_conf
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db_conf_only):
            # Entry point prompts for PIN
            xml_entry = await handle_dialplan_request({
                "Caller-Context": "default",
                "Caller-Destination-Number": "3500",
                "domain": "pbx.test.local",
                "variable_tenant_id": "tid-e2e"
            })
            self.assertIn('application="play_and_get_digits"', xml_entry)
            self.assertIn('conf_exec_3500_${entered_conf_pin}', xml_entry)

            # Execution with Moderator PIN
            xml_mod = await handle_dialplan_request({
                "Caller-Context": "default",
                "Caller-Destination-Number": "conf_exec_3500_9999",
                "domain": "pbx.test.local",
                "variable_tenant_id": "tid-e2e"
            })
            self.assertIn('data="Executive Room@default+flags{moderator}"', xml_mod)
            self.assertIn('application="record_session"', xml_mod)

            # Execution with Participant PIN
            xml_part = await handle_dialplan_request({
                "Caller-Context": "default",
                "Caller-Destination-Number": "conf_exec_3500_1234",
                "domain": "pbx.test.local",
                "variable_tenant_id": "tid-e2e"
            })
            self.assertIn('data="Executive Room@default"', xml_part)
            self.assertNotIn('+flags{moderator}', xml_part)

            # Execution with Invalid PIN
            xml_inv = await handle_dialplan_request({
                "Caller-Context": "default",
                "Caller-Destination-Number": "conf_exec_3500_0000",
                "domain": "pbx.test.local",
                "variable_tenant_id": "tid-e2e"
            })
            self.assertIn('conference/conf-bad-pin.wav', xml_inv)
            self.assertIn('data="CALL_REJECTED"', xml_inv)

if __name__ == "__main__":
    unittest.main()
