import asyncio
import httpx

async def verify_all():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # 1. Login as tenant admin
        login_res = await client.post("/api/v1/auth/login", data={"username": "aikyamadmin", "password": "aikyampassword123"})
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print("1. Tenant Admin Login: SUCCESS")

        # 2. Test Business Hours Create & Delete
        bh_list = await client.get("/api/v1/business-hours", headers=headers)
        print(f"2a. List Business Hours: {bh_list.status_code}, count={len(bh_list.json())}")
        bh_create = await client.post("/api/v1/business-hours", headers=headers, json={
            "name": "Verification Test Schedule",
            "timezone": "Asia/Kolkata",
            "schedule": [{"day_of_week": 1, "start_time": "09:00", "end_time": "17:00"}]
        })
        assert bh_create.status_code in (200, 201), f"Create BH failed: {bh_create.text}"
        bh_id = bh_create.json()["id"]
        print(f"2b. Create Business Hours: SUCCESS (id={bh_id})")
        bh_del = await client.delete(f"/api/v1/business-hours/{bh_id}", headers=headers)
        assert bh_del.status_code == 204, f"Delete BH failed: {bh_del.status_code} {bh_del.text}"
        print("2c. Delete Business Hours: SUCCESS (204 No Content)")

        # 3. Test Call Recording Streaming
        rec_list = await client.get("/api/v1/reports/recordings", headers=headers)
        assert rec_list.status_code == 200, f"List rec failed: {rec_list.text}"
        recs = rec_list.json().get("items", [])
        print(f"3a. List Recordings: count={len(recs)}")
        if recs:
            rec_id = recs[0]["id"]
            stream_res = await client.get(f"/api/v1/reports/recordings/{rec_id}/stream", headers=headers)
            assert stream_res.status_code == 200, f"Stream rec failed: {stream_res.status_code}"
            ctype = stream_res.headers.get("content-type")
            print(f"3b. Stream Recording {rec_id}: SUCCESS (200 OK, {len(stream_res.content)} bytes, {ctype})")

        # 4. Test Call Forwarding XML Dialplan
        # 4a. Incoming call to 1001 from 9001
        dp_res_1 = await client.post("/freeswitch/xml", data={
            "section": "dialplan",
            "Caller-Destination-Number": "1001",
            "Caller-Caller-ID-Number": "9001",
            "Caller-Context": "tenant-9c61b161-db6f-4825-b7db-cb76d88155c5",
            "domain": "pbx.aikyamlabs.local"
        })
        assert dp_res_1.status_code == 200
        xml_1 = dp_res_1.text
        assert "call_timeout=10" in xml_1, f"Missing call_timeout=10 in: {xml_1}"
        assert "originate_timeout=10" in xml_1, f"Missing originate_timeout=10 in: {xml_1}"
        assert "ignore_early_media=true" in xml_1, f"Missing ignore_early_media=true in: {xml_1}"
        assert "transfer_on_fail=fwd_no_answer_1001" in xml_1, f"Missing transfer_on_fail=fwd_no_answer_1001 in: {xml_1}"
        assert "fwd_no_answer_1001" in xml_1, f"Missing fwd_no_answer_1001 extension in: {xml_1}"
        print("4a. Dialplan for call to 1001 (caller 9001): SUCCESS (timeout=10s, failover target=fwd_no_answer_1001)")

        # 4b. Failover request for fwd_no_answer_1001
        dp_res_2 = await client.post("/freeswitch/xml", data={
            "section": "dialplan",
            "Caller-Destination-Number": "fwd_no_answer_1001",
            "Caller-Caller-ID-Number": "9001",
            "Caller-Context": "tenant-9c61b161-db6f-4825-b7db-cb76d88155c5",
            "domain": "pbx.aikyamlabs.local"
        })
        assert dp_res_2.status_code == 200
        xml_2 = dp_res_2.text
        assert 'data="9001 XML tenant-9c61b161-db6f-4825-b7db-cb76d88155c5"' in xml_2, f"Unexpected XML: {xml_2}"
        print("4b. Dialplan for failover fwd_no_answer_1001: SUCCESS (transfers to 9001 XML context)")
        print("\nALL VERIFICATIONS PASSED!")

if __name__ == "__main__":
    asyncio.run(verify_all())
