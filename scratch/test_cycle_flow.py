import asyncio
import datetime
import httpx
import jwt
from app.core.config import settings

async def test_cycle_flow():
    user_id = "7521eccc-f04c-45f5-b59d-7a1d7ad4b1ee"
    secret = settings.SUPABASE_JWT_SECRET
    if hasattr(secret, "get_secret_value"):
        secret = secret.get_secret_value()
    secret = str(secret).strip()

    token = jwt.encode(
        {
            "sub": user_id,
            "email": "bitterfiish@gmail.com",
            "aud": "authenticated",
            "iss": f"{settings.SUPABASE_URL}/auth/v1",
            "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1),
        },
        secret,
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        print("--- 1. Current cycle state ---")
        res1 = await client.get("/api/v1/cycles/current", headers=headers)
        print("GET /api/v1/cycles/current ->", res1.status_code, res1.json())

        print("\n--- 2. End ongoing period (TEST 1) ---")
        res2 = await client.post(
            "/api/v1/cycles/current/end",
            headers=headers,
            json={"period_end": "2026-09-08"}
        )
        print("POST /api/v1/cycles/current/end ->", res2.status_code, res2.json())

        print("\n--- 3. Verify current cycle after ending ---")
        res3 = await client.get("/api/v1/cycles/current", headers=headers)
        print("GET /api/v1/cycles/current ->", res3.status_code, res3.json())

        print("\n--- 4. Start new period (TEST 2) ---")
        res4 = await client.post(
            "/api/v1/cycles",
            headers=headers,
            json={"period_start": "2026-09-08"}
        )
        print("POST /api/v1/cycles ->", res4.status_code, res4.json())

        print("\n--- 5. Verify current cycle after starting ---")
        res5 = await client.get("/api/v1/cycles/current", headers=headers)
        print("GET /api/v1/cycles/current ->", res5.status_code, res5.json())

if __name__ == "__main__":
    asyncio.run(test_cycle_flow())
