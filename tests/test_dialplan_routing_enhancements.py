# tests/test_dialplan_routing_enhancements.py
import unittest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

class TestDialplanRoutingEnhancements(unittest.IsolatedAsyncioTestCase):

    async def test_outbound_fails_when_no_gateway_assigned(self):
        """When a tenant has no gateway assigned, outbound calls must fail with 403."""
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "9890567567",
            "Caller-Caller-ID-Number": "1001",
            "variable_tenant_id": "11111111-1111-1111-1111-111111111111",
            "domain": "pbx.terrixai.com"
        }

        async def mock_db(query, params=None):
            # No gateway, route, or trunk returned
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn("403 Forbidden - No Gateway Assigned", xml_res)
            self.assertIn("CALL_REJECTED", xml_res)

    async def test_internal_extension_works_without_gateway(self):
        """Internal extension-to-extension calls work even when tenant has no gateway."""
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "1002",
            "Caller-Caller-ID-Number": "1001",
            "variable_tenant_id": "11111111-1111-1111-1111-111111111111",
            "domain": "pbx.terrixai.com"
        }
        mock_ext = {
            "id": "ext-1002",
            "extension_number": "1002",
            "display_name": "Bob",
            "caller_id_name": "Bob",
            "caller_id_number": "1002",
            "email": "bob@test.com",
            "enabled": True,
            "no_answer_timeout": 15,
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "sip_domain": "pbx.terrixai.com"
        }
        mock_tenant = {
            "id": "11111111-1111-1111-1111-111111111111",
            "allow_internal_calls": True,
            "sip_domain": "pbx.terrixai.com"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from extensions" in q:
                return mock_ext
            if "from tenants" in q:
                return mock_tenant
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('user/1002@pbx.terrixai.com', xml_res)
            self.assertIn('hangup_after_bridge=true', xml_res)
            self.assertNotIn("403 Forbidden - No Gateway Assigned", xml_res)

    async def test_inbound_routing_to_ivr_by_name(self):
        """Inbound DID routing to IVR matches by name and executes play_and_get_digits."""
        form_data = {
            "Caller-Context": "public",
            "Caller-Destination-Number": "+919890567567",
            "domain": "pbx.terrixai.com"
        }
        mock_route = {
            "id": "route-1",
            "destination_type": "ivr",
            "destination": "Main IVR Flow",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "sip_domain": "pbx.terrixai.com"
        }
        mock_ivr = {
            "id": "ivr-uuid-1",
            "name": "Main IVR Flow",
            "extension_number": "6001",
            "timeout": 8,
            "greeting_audio": "welcome.wav"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from call_routes" in q:
                return mock_route
            if "from ivr_menus" in q:
                return mock_ivr
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('application="play_and_get_digits"', xml_res)
            self.assertIn('ivr_menu_id=ivr-uuid-1', xml_res)
            self.assertIn('ivr_choice_${dtmf_result}', xml_res)

    async def test_inbound_routing_to_hunt_group_sequential(self):
        """Inbound DID routing to hunt group with sequential strategy bridges with pipe separator."""
        form_data = {
            "Caller-Context": "public",
            "Caller-Destination-Number": "+919890567567",
            "domain": "pbx.terrixai.com"
        }
        mock_route = {
            "id": "route-2",
            "destination_type": "hunt_group",
            "destination": "Sales Team",
            "tenant_id": "11111111-1111-1111-1111-111111111111",
            "sip_domain": "pbx.terrixai.com"
        }
        mock_hg = {
            "id": "hg-1",
            "name": "Sales Team",
            "extension_number": "8787",
            "strategy": "sequential",
            "members": "1001, 1002, 1003",
            "timeout": 20,
            "tenant_id": "11111111-1111-1111-1111-111111111111"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from call_routes" in q:
                return mock_route
            if "from hunt_groups" in q:
                return mock_hg
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('application="bridge"', xml_res)
            self.assertIn("user/1001@pbx.terrixai.com|user/1002@pbx.terrixai.com|user/1003@pbx.terrixai.com", xml_res)

if __name__ == "__main__":
    unittest.main()
