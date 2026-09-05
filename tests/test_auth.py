import pytest
from httpx import AsyncClient


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


@pytest.mark.asyncio
async def test_auth_valid_token_me(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "user_id" in data
    assert data["user_id"] == "11111111-2222-3333-4444-555555555555"
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
