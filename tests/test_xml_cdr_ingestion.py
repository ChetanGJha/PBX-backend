import unittest
from unittest.mock import patch, AsyncMock
from src.xml_curl.router import parse_xml_cdr_to_dict, process_cdr_record

class TestXmlCdrIngestion(unittest.IsolatedAsyncioTestCase):
    def test_parse_xml_cdr_structure(self):
        sample_xml = """<?xml version="1.0"?>
        <cdr core-uuid="fs-core-1">
          <variables>
            <uuid>call-test-uuid-1234</uuid>
            <direction>inbound</direction>
            <caller_id_number>+18005550199</caller_id_number>
            <caller_id_name>Customer One</caller_id_name>
            <destination_number>1001</destination_number>
            <tenant_id>11111111-1111-1111-1111-111111111111</tenant_id>
            <start_epoch>1700000000</start_epoch>
            <answer_epoch>1700000005</answer_epoch>
            <end_epoch>1700000045</end_epoch>
            <duration>45</duration>
            <billsec>40</billsec>
            <hangup_cause>NORMAL_CLEARING</hangup_cause>
            <hangup_cause_q850>16</hangup_cause_q850>
          </variables>
        </cdr>
        """
        data = parse_xml_cdr_to_dict(sample_xml)
        self.assertIn("variables", data)
        self.assertEqual(data["variables"]["uuid"], "call-test-uuid-1234")
        self.assertEqual(data["variables"]["direction"], "inbound")
        self.assertEqual(data["variables"]["duration"], "45")
        self.assertEqual(data["variables"]["billsec"], "40")
        self.assertEqual(data["variables"]["caller_id_number"], "+18005550199")

    async def test_process_cdr_record_direction_detection(self):
        # 1. Internal Extension Call direction
        cdr_data_internal = {
            "variables": {
                "uuid": "call-int-1",
                "caller_id_number": "1001",
                "caller_id_name": "Alice",
                "destination_number": "1002",
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "start_epoch": "1700000000",
                "answer_epoch": "1700000005",
                "end_epoch": "1700000030",
                "duration": "30",
                "billsec": "25",
                "hangup_cause": "NORMAL_CLEARING"
            }
        }
        with patch("src.xml_curl.router.execute_query", new_callable=AsyncMock) as mock_exec:
            res = await process_cdr_record(cdr_data_internal)
            self.assertEqual(res["direction"], "internal")
            self.assertEqual(res["call_uuid"], "call-int-1")
            self.assertEqual(res["duration"], 30)
            self.assertEqual(res["billsec"], 25)
            self.assertTrue(mock_exec.called)

        # 2. Outbound Call direction
        cdr_data_outbound = {
            "variables": {
                "uuid": "call-out-1",
                "caller_id_number": "1001",
                "destination_number": "+919876543210",
                "direction": "outbound",
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "start_epoch": "1700000000",
                "answer_epoch": "1700000010",
                "end_epoch": "1700000060",
                "duration": "60",
                "billsec": "50",
                "hangup_cause": "NORMAL_CLEARING"
            }
        }
        with patch("src.xml_curl.router.execute_query", new_callable=AsyncMock) as mock_exec:
            res_out = await process_cdr_record(cdr_data_outbound)
            self.assertEqual(res_out["direction"], "outbound")
            self.assertEqual(res_out["destination"], "+919876543210")

if __name__ == "__main__":
    unittest.main()
