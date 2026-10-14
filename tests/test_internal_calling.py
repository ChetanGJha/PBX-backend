# tests/test_internal_calling.py
import unittest
from unittest.mock import patch
from src.xml_curl.dialplan import handle_dialplan_request

class TestInternalCalling(unittest.IsolatedAsyncioTestCase):
    async def test_internal_calling_disabled_rejects_call(self):
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "1002",
            "Caller-Caller-ID-Number": "1001",
            "domain": "pbx.aikyamlabs.local",
            "variable_tenant_id": "11111111-1111-1111-1111-111111111111"
        }
        mock_tenant = {
            "id": "11111111-1111-1111-1111-111111111111",
            "allow_internal_calls": False,
            "sip_domain": "pbx.aikyamlabs.local"
        }
        mock_target_ext = {
            "id": "22222222-2222-2222-2222-222222222222",
            "extension_number": "1002",
            "sip_domain": "pbx.aikyamlabs.local"
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from extensions" in q:
                return mock_target_ext
            if "from tenants" in q:
                return mock_tenant
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn("403", xml_res)
            self.assertIn("CALL_REJECTED", xml_res)

    async def test_internal_calling_enabled_bridges_natively(self):
        form_data = {
            "Caller-Context": "default",
            "Caller-Destination-Number": "1002",
            "Caller-Caller-ID-Number": "1001",
            "domain": "pbx.aikyamlabs.local",
            "variable_tenant_id": "11111111-1111-1111-1111-111111111111"
        }
        mock_tenant = {
            "id": "11111111-1111-1111-1111-111111111111",
            "allow_internal_calls": True,
            "sip_domain": "pbx.aikyamlabs.local"
        }
        mock_target_ext = {
            "id": "22222222-2222-2222-2222-222222222222",
            "extension_number": "1002",
            "sip_domain": "pbx.aikyamlabs.local",
            "no_answer_timeout": 20
        }

        async def mock_db(query, params=None):
            q = query.lower()
            if "from extensions" in q:
                return mock_target_ext
            if "from tenants" in q:
                return mock_tenant
            return None

        with patch("src.xml_curl.dialplan.execute_query_one", side_effect=mock_db):
            xml_res = await handle_dialplan_request(form_data)
            self.assertIn("user/1002@pbx.aikyamlabs.local", xml_res)
            self.assertIn("continue_on_fail=true", xml_res)
            self.assertIn("voicemail_1002", xml_res)

if __name__ == "__main__":
    unittest.main()
