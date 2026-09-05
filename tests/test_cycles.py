from datetime import date, timedelta
import pytest
from httpx import AsyncClient

from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID


@pytest.mark.asyncio
async def test_cycle_lifecycle_and_summary(async_client: AsyncClient, auth_headers: dict):
    # 1. Initially no periods logged
    cur_res = await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    assert cur_res.status_code == 200
    cur_data = cur_res.json()
    assert cur_data["has_data"] is False
    assert cur_data["predicted_next_period"] is None
    assert cur_data["prediction_source"] == "insufficient_data"

    # 2. Log period
    p_start = date.today() - timedelta(days=10)
    p_end = date.today() - timedelta(days=6)
    create_res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(p_start), "period_end": str(p_end)},
    )
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["period_start"] == str(p_start)
    assert created["period_end"] == str(p_end)
    assert created["period_length_days"] == 5

    # 3. List cycles
    list_res = await async_client.get("/api/v1/cycles", headers=auth_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1


@pytest.mark.asyncio
async def test_cycle_overlapping_and_validation(async_client: AsyncClient, auth_headers: dict):
    # Create valid base period: 20 days ago to 15 days ago
    start_1 = date.today() - timedelta(days=20)
    end_1 = date.today() - timedelta(days=15)
    res1 = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(start_1), "period_end": str(end_1)},
    )
    assert res1.status_code == 201

    # Overlapping period (18 days ago to 12 days ago)
    res_overlap = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(date.today() - timedelta(days=18)), "period_end": str(date.today() - timedelta(days=12))},
    )
    assert res_overlap.status_code == 400
    assert "overlaps with existing period" in res_overlap.json()["detail"]

    # Duplicate start date
    res_dup = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(start_1), "period_end": None},
    )
    assert res_dup.status_code == 400

    # Period end prior to start
    res_end_before_start = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(date.today() - timedelta(days=5)), "period_end": str(date.today() - timedelta(days=7))},
    )
    assert res_end_before_start.status_code == 422

    # Future period start (> tomorrow)
    res_future = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(date.today() + timedelta(days=10))},
    )
    assert res_future.status_code == 422


@pytest.mark.asyncio
async def test_cross_user_cycle_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    # User 1 logs a cycle
    p_start = date.today() - timedelta(days=14)
    p_end = date.today() - timedelta(days=10)
    await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(p_start), "period_end": str(p_end)},
    )

    # User 2 lists cycles -> should be empty
    res2 = await async_client.get("/api/v1/cycles", headers=other_user_auth_headers)
    assert res2.status_code == 200
    assert len(res2.json()) == 0
