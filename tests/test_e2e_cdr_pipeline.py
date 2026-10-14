import os
import unittest
import urllib.parse
from uuid import uuid4
import requests

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
WS_HOST = os.getenv("WS_HOST", "127.0.0.1:8000")

SAMPLE_XML_TEMPLATE = """<?xml version="1.0"?>
<cdr core-uuid="freeswitch-core-1">
  <channel_data>
    <state>CS_HANGUP</state>
    <direction>{direction}</direction>
  </channel_data>
  <variables>
    <uuid>{uuid}</uuid>
    <sip_from_user>{caller}</sip_from_user>
    <caller_id_number>{caller}</caller_id_number>
    <destination_number>{destination}</destination_number>
    <duration>{duration}</duration>
    <billsec>{billsec}</billsec>
    <hangup_cause>{hangup_cause}</hangup_cause>
    <hangup_cause_q850>16</hangup_cause_q850>
    <start_epoch>{start_epoch}</start_epoch>
    <answer_epoch>{answer_epoch}</answer_epoch>
    <end_epoch>{end_epoch}</end_epoch>
  </variables>
  <callflow>
    <caller_profile>
      <caller_id_number>{caller}</caller_id_number>
      <destination_number>{destination}</destination_number>
    </caller_profile>
    <times>
      <created_time>{start_epoch}000000</created_time>
      <answered_time>{answer_epoch}000000</answered_time>
      <hangup_time>{end_epoch}000000</hangup_time>
    </times>
  </callflow>
</cdr>"""

class TestE2ECdrPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import jwt
        from datetime import datetime, timezone, timedelta
        secret = "super-secret-jwt-signing-key-change-this-in-production-min-32-chars"
        user_id = "0c909c30-0116-45ab-91c7-b16ec662ee4a"
        cls.token = jwt.encode({
            "sub": user_id,
            "user_id": user_id,
            "email": "admin@pbx.com",
            "username": "superadmin",
            "role": "SUPER_ADMIN",
            "tenant_id": None,
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1)
        }, secret, algorithm="HS256")
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    def test_full_cdr_pipeline_reports_and_telemetry(self):
        import time
        now = int(time.time())

        # 1. Ingest Inbound Call (Answered)
        inbound_uuid = str(uuid4())
        inbound_xml = SAMPLE_XML_TEMPLATE.format(
            uuid=inbound_uuid,
            direction="inbound",
            caller="+15551234567",
            destination="1001",
            duration=45,
            billsec=45,
            hangup_cause="NORMAL_CLEARING",
            start_epoch=now - 50,
            answer_epoch=now - 45,
            end_epoch=now - 5
        )
        res1 = requests.post(
            f"{API_URL}/freeswitch/cdr",
            data=f"cdr={urllib.parse.quote_plus(inbound_xml)}".encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        self.assertEqual(res1.status_code, 200)

        # 2. Ingest Outbound Call (Busy)
        outbound_uuid = str(uuid4())
        outbound_xml = SAMPLE_XML_TEMPLATE.format(
            uuid=outbound_uuid,
            direction="outbound",
            caller="1001",
            destination="+15559876543",
            duration=12,
            billsec=0,
            hangup_cause="USER_BUSY",
            start_epoch=now - 30,
            answer_epoch=0,
            end_epoch=now - 18
        )
        res2 = requests.post(
            f"{API_URL}/freeswitch/cdr",
            data=f"cdr={urllib.parse.quote_plus(outbound_xml)}".encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        self.assertEqual(res2.status_code, 200)

        # 3. Ingest Internal Call (No Answer)
        internal_uuid = str(uuid4())
        internal_xml = SAMPLE_XML_TEMPLATE.format(
            uuid=internal_uuid,
            direction="internal",
            caller="1001",
            destination="1002",
            duration=30,
            billsec=0,
            hangup_cause="NO_ANSWER",
            start_epoch=now - 35,
            answer_epoch=0,
            end_epoch=now - 5
        )
        res3 = requests.post(
            f"{API_URL}/freeswitch/cdr",
            data=f"cdr={urllib.parse.quote_plus(internal_xml)}".encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        self.assertEqual(res3.status_code, 200)

        # 4. Query Disposition Summary
        disp_res = requests.get(f"{API_URL}/api/v1/reports/disposition-summary", headers=self.headers)
        self.assertEqual(disp_res.status_code, 200)
        disp_data = disp_res.json()
        self.assertGreaterEqual(disp_data["total_calls"], 3)
        self.assertGreaterEqual(disp_data["answered"], 1)
        self.assertGreaterEqual(disp_data["busy"], 1)
        self.assertGreaterEqual(disp_data["no_answer"], 1)
        self.assertGreater(disp_data["answer_rate"], 0.0)
        self.assertTrue(len(disp_data["breakdown"]) > 0)

        # 5. Query CDR with direction filter
        cdr_res_in = requests.get(f"{API_URL}/api/v1/reports/cdr?direction=inbound", headers=self.headers)
        self.assertEqual(cdr_res_in.status_code, 200)
        inbound_records = cdr_res_in.json()
        self.assertTrue(any(r["call_uuid"] == inbound_uuid for r in inbound_records))

        # 6. Query CDR with disposition filter
        cdr_res_ans = requests.get(f"{API_URL}/api/v1/reports/cdr?disposition=ANSWERED", headers=self.headers)
        self.assertEqual(cdr_res_ans.status_code, 200)
        ans_records = cdr_res_ans.json()
        self.assertTrue(any(r["call_uuid"] == inbound_uuid for r in ans_records))

        # 7. Query Dashboard Metrics (Traffic Summary and Peak)
        dash_res = requests.get(f"{API_URL}/api/v1/reports/dashboard-metrics", headers=self.headers)
        self.assertEqual(dash_res.status_code, 200)
        dash_data = dash_res.json()
        
        # Verify traffic summary populated
        traffic_sum = dash_data["traffic_summary"]
        self.assertGreaterEqual(traffic_sum["inbound"]["total"], 1)
        self.assertGreaterEqual(traffic_sum["inbound"]["answered"], 1)
        self.assertGreaterEqual(traffic_sum["outbound"]["total"], 1)
        self.assertGreaterEqual(traffic_sum["outbound"]["unanswered"], 1)

        # Verify traffic peak populated
        traffic_peak = dash_data["traffic_peak"]
        self.assertGreaterEqual(traffic_peak["inbound_peak"], 1)
        self.assertGreaterEqual(traffic_peak["outbound_peak"], 1)

        # Verify live_calls present and numeric
        self.assertIsInstance(dash_data["live_calls"], int)

    def test_realtime_websocket_cdr_broadcast(self):
        import asyncio
        import websockets
        import json
        import time

        async def _run_ws_test():
            ws_url = f"ws://{WS_HOST}/ws/reports?token={self.token}"
            async with websockets.connect(ws_url) as ws:
                # Post a CDR
                call_uuid = str(uuid4())
                now = int(time.time())
                xml_data = SAMPLE_XML_TEMPLATE.format(
                    uuid=call_uuid,
                    direction="inbound",
                    caller="+15553334444",
                    destination="1001",
                    duration=20,
                    billsec=20,
                    hangup_cause="NORMAL_CLEARING",
                    start_epoch=now - 20,
                    answer_epoch=now - 15,
                    end_epoch=now
                )
                res = requests.post(
                    f"{API_URL}/freeswitch/cdr",
                    data=f"cdr={urllib.parse.quote_plus(xml_data)}".encode(),
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                self.assertEqual(res.status_code, 200)

                # Wait for broadcast on websocket
                msg_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                msg = json.loads(msg_raw)
                self.assertEqual(msg.get("event"), "cdr.created")
                self.assertEqual(msg.get("data", {}).get("call_uuid"), call_uuid)

        asyncio.run(_run_ws_test())

if __name__ == "__main__":
    unittest.main()
