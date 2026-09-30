import asyncio
import httpx
from src.core.security import create_access_token
from src.core.database import execute_query_one

async def main():
    user = await execute_query_one("SELECT id, tenant_id FROM users WHERE username = 'superadmin'")
    if not user:
        user = await execute_query_one("SELECT id, tenant_id FROM users LIMIT 1")
    
    token = create_access_token(user["id"], role="SUPER_ADMIN", tenant_id=user["tenant_id"])
    headers = {"Authorization": f"Bearer {token}"}
    
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        # 1. Test CDR
        res = await client.get("/api/v1/reports/cdr", headers=headers)
        print("GET /api/v1/reports/cdr status:", res.status_code, "count:", len(res.json()))
        if res.json():
            print("  CDR sample:", list(res.json()[0].keys()))

        # 2. Test Recordings
        res = await client.get("/api/v1/reports/recordings", headers=headers)
        print("GET /api/v1/reports/recordings status:", res.status_code, "count:", len(res.json()))
        if res.json():
            print("  Recordings sample:", res.json()[0].get("file_name"), "created_at:", res.json()[0].get("created_at"))
            rec_id = res.json()[0]["id"]
            # Test stream
            stream_res = await client.get(f"/api/v1/reports/recordings/{rec_id}/stream", headers=headers)
            print(f"  Stream recording {rec_id} status:", stream_res.status_code, "content-type:", stream_res.headers.get("content-type"))

        # 3. Test Outbound
        res = await client.get("/api/v1/reports/outbound", headers=headers)
        print("GET /api/v1/reports/outbound status:", res.status_code, "count:", len(res.json()))
        if res.json():
            print("  Outbound sample:", res.json()[0].get("caller_id_number"), "->", res.json()[0].get("destination_number"), "start_stamp:", res.json()[0].get("start_stamp"))

        # 4. Test Internal
        res = await client.get("/api/v1/reports/internal", headers=headers)
        print("GET /api/v1/reports/internal status:", res.status_code, "count:", len(res.json()))
        if res.json():
            for row in res.json():
                print("  Internal call row:", row)

        # 5. Test Trunks
        res = await client.get("/api/v1/trunks", headers=headers)
        print("GET /api/v1/trunks status:", res.status_code, "count:", len(res.json()))
        if res.json():
            trunk = res.json()[0]
            print("  Trunk sample:", trunk.get("name"), "tenant:", trunk.get("tenant_name"))

        # 6. Test Gateways
        res = await client.get("/api/v1/gateways", headers=headers)
        print("GET /api/v1/gateways status:", res.status_code, "count:", len(res.json()))

if __name__ == "__main__":
    asyncio.run(main())
