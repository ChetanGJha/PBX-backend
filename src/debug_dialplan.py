import asyncio
import httpx

async def main():
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        form_data = {
            "section": "dialplan",
            "Caller-Context": "tenant-9c61b161-db6f-4825-b7db-cb76d88155c5",
            "Caller-Destination-Number": "voicemail_1001",
            "Caller-Caller-ID-Number": "9001",
            "variable_sip_to_user": "voicemail_1001",
            "variable_sip_req_host": "127.0.0.1"
        }
        res = await client.post("/freeswitch/xml", data=form_data)
        print("STATUS:", res.status_code)
        print("BODY:\n", res.text)

if __name__ == "__main__":
    asyncio.run(main())
