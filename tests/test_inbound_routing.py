# tests/test_inbound_routing.py
import unittest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

class TestInboundRouting(unittest.IsolatedAsyncioTestCase):
    async def test_inbound_routing_to_queue(self):
        form_data = {
            "Caller-Context": "public",
            "Caller-Destination-Number": "+15552000",
            "domain": "8.234.117.15"
        }
        mock_route = {
            "id": "uuid-route",
            "destination_type": "queue",
            "destination": "Support_Queue",
            "tenant_id": "tid-1",
            "sip_domain": "pbx.aikyamlabs.local"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from call_routes" in q:
                return mock_route
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn('application="callcenter"', xml_res)
            self.assertIn('data="Support_Queue"', xml_res)

    async def test_inbound_routing_to_hunt_group(self):
        form_data = {
            "Caller-Context": "public",
            "Caller-Destination-Number": "+15553000",
            "domain": "8.234.117.15"
        }
        mock_route = {
            "id": "uuid-route",
            "destination_type": "hunt_group",
            "destination": "8888",
            "tenant_id": "tid-1",
            "sip_domain": "pbx.aikyamlabs.local"
        }
        mock_hg = {
            "name": "Sales Group",
            "extension_number": "8888",
            "members": "1001, 1002",
            "timeout": 20,
            "tenant_id": "tid-1"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from call_routes" in q:
                return mock_route
            if "from hunt_groups" in q:
                return mock_hg
            if "from tenants" in q:
                return {"id": "tid-1", "sip_domain": "pbx.aikyamlabs.local"}
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn("user/1001@pbx.aikyamlabs.local", xml_res)
            self.assertIn("user/1002@pbx.aikyamlabs.local", xml_res)

    async def test_inbound_routing_to_extension(self):
        form_data = {
            "Caller-Context": "public",
            "Caller-Destination-Number": "+15551000",
            "domain": "8.234.117.15"
        }
        mock_route = {
            "id": "uuid-route",
            "destination_type": "extension",
            "destination": "1001",
            "tenant_id": "tid-1",
            "sip_domain": "pbx.aikyamlabs.local"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from call_routes" in q:
                return mock_route
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn("user/1001@pbx.aikyamlabs.local", xml_res)
            self.assertIn("continue_on_fail=", xml_res)

if __name__ == "__main__":
    unittest.main()
