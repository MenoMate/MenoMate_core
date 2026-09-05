from datetime import datetime, timedelta, timezone
import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID


@pytest.mark.asyncio
async def test_auth_missing_token(async_client: AsyncClient):
    res = await async_client.get("/api/v1/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_auth_invalid_token(async_client: AsyncClient):
    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert res.status_code == 401
    assert "Could not validate credentials" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_malformed_token(async_client: AsyncClient):
    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.payload.structure"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_auth_expired_token(async_client: AsyncClient):
    # Expired token in the past
    past_exp = datetime.now(timezone.utc) - timedelta(minutes=10)
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(past_exp.timestamp()),
    }
    expired_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == 401
    assert "Token has expired" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_invalid_audience(async_client: AsyncClient):
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "unauthorized_audience",
        "role": "authenticated",
    }
    bad_aud_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bad_aud_token}"},
    )
    assert res.status_code == 401
    assert "Invalid token audience" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_invalid_issuer(async_client: AsyncClient):
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": "https://malicious-issuer.com/auth/v1",
        "role": "authenticated",
    }
    bad_iss_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bad_iss_token}"},
    )
    assert res.status_code == 401
    assert "Invalid token issuer" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_valid_token_me(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "user_id" in data
    assert data["user_id"] == str(TEST_USER_ID)
    assert data["theme"] == "system"
    assert data["units"] == "metric"


@pytest.mark.asyncio
async def test_profile_update_and_delete(async_client: AsyncClient, auth_headers: dict):
    # Update profile
    patch_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"name": "Aria", "theme": "dark", "usual_cycle_days": 30},
    )
    assert patch_res.status_code == 200
    p_data = patch_res.json()
    assert p_data["name"] == "Aria"
    assert p_data["theme"] == "dark"
    assert p_data["usual_cycle_days"] == 30

    # Get profile
    get_res = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Aria"

    # Delete profile
    del_res = await async_client.delete("/api/v1/profile", headers=auth_headers)
    assert del_res.status_code == 204


@pytest.mark.asyncio
async def test_cross_user_profile_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    # User 1 sets their name
    await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"name": "User One"},
    )

    # User 2 sets their name
    await async_client.patch(
        "/api/v1/profile",
        headers=other_user_auth_headers,
        json={"name": "User Two"},
    )

    # User 1 gets their profile
    res1 = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res1.json()["name"] == "User One"
    assert res1.json()["user_id"] == str(TEST_USER_ID)

    # User 2 gets their profile
    res2 = await async_client.get("/api/v1/profile", headers=other_user_auth_headers)
    assert res2.json()["name"] == "User Two"
    assert res2.json()["user_id"] == str(ANOTHER_USER_ID)
