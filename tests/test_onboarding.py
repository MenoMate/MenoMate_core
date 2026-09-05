from datetime import date, timedelta
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_onboarding_normal_flow(async_client: AsyncClient, auth_headers: dict):
    start = date.today() - timedelta(days=3)
    end = date.today()
    payload = {
        "name": "Maya",
        "last_period_start": str(start),
        "last_period_end": str(end),
        "usual_cycle_days": 29,
        "usual_period_days": 5,
    }

    res = await async_client.post("/api/v1/onboarding/complete", headers=auth_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["message"] == "Onboarding completed successfully."
    assert data["period_start"] == str(start)
    assert data["period_end"] == str(end)
    assert data["profile"]["usual_cycle_days"] == 29


@pytest.mark.asyncio
async def test_onboarding_unsure_null_values(async_client: AsyncClient, auth_headers: dict):
    start = date.today() - timedelta(days=2)
    payload = {
        "name": "Jordan",
        "last_period_start": str(start),
        "last_period_end": None,
        "usual_cycle_days": None,  # "I'm not sure"
        "usual_period_days": None, # "I'm not sure"
    }

    res = await async_client.post("/api/v1/onboarding/complete", headers=auth_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["period_start"] == str(start)
    assert data["period_end"] is None
    assert data["profile"]["usual_cycle_days"] is None
    assert data["profile"]["usual_period_days"] is None


@pytest.mark.asyncio
async def test_onboarding_idempotency_safe_repeated(async_client: AsyncClient, auth_headers: dict):
    start = date(2026, 8, 1)
    payload = {
        "name": "Elena",
        "last_period_start": str(start),
        "last_period_end": str(date(2026, 8, 5)),
        "usual_cycle_days": 28,
        "usual_period_days": 5,
    }

    # First call
    res1 = await async_client.post("/api/v1/onboarding/complete", headers=auth_headers, json=payload)
    assert res1.status_code == 201
    p1_id = res1.json()["period_id"]

    # Repeated call with same start date
    res2 = await async_client.post("/api/v1/onboarding/complete", headers=auth_headers, json=payload)
    assert res2.status_code == 201
    p2_id = res2.json()["period_id"]

    assert p1_id == p2_id  # Reused existing period without creating duplicate
