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


@pytest.mark.asyncio
async def test_patch_cycle_null_reopen_ongoing(async_client: AsyncClient, auth_headers: dict):
    # 1. Create a closed period
    start = date(2026, 6, 1)
    end = date(2026, 6, 5)
    create_res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(start), "period_end": str(end)},
    )
    assert create_res.status_code == 201
    cycle_id = create_res.json()["id"]
    assert create_res.json()["period_end"] == str(end)
    assert create_res.json()["period_length_days"] == 5

    # 2. PATCH with {"period_end": None} explicitly to reopen ongoing period
    patch_res = await async_client.patch(
        f"/api/v1/cycles/{cycle_id}",
        headers=auth_headers,
        json={"period_end": None},
    )
    assert patch_res.status_code == 200
    patch_data = patch_res.json()
    assert patch_data["period_end"] is None
    assert patch_data["period_length_days"] is None  # Bleeding still ongoing

    # 3. PATCH with omitted period_end (only period_start) should not alter period_end
    patch_res2 = await async_client.patch(
        f"/api/v1/cycles/{cycle_id}",
        headers=auth_headers,
        json={"period_start": str(date(2026, 6, 2))},
    )
    assert patch_res2.status_code == 200
    assert patch_res2.json()["period_start"] == str(date(2026, 6, 2))
    assert patch_res2.json()["period_end"] is None

    # 4. Close it again
    patch_res3 = await async_client.patch(
        f"/api/v1/cycles/{cycle_id}",
        headers=auth_headers,
        json={"period_end": str(date(2026, 6, 6))},
    )
    assert patch_res3.status_code == 200
    assert patch_res3.json()["period_end"] == str(date(2026, 6, 6))
    assert patch_res3.json()["period_length_days"] == 5


@pytest.mark.asyncio
async def test_future_period_not_reported_as_bleeding_today(async_client: AsyncClient, other_user_auth_headers: dict):
    # Use other_user to have a clean state without prior periods
    tomorrow = date.today() + timedelta(days=1)

    # 1. Log period starting tomorrow (allowed under +1 day timezone variance)
    res = await async_client.post(
        "/api/v1/cycles",
        headers=other_user_auth_headers,
        json={"period_start": str(tomorrow), "period_end": None},
    )
    assert res.status_code == 201

    # 2. Check current summary
    summary_res = await async_client.get("/api/v1/summary/current", headers=other_user_auth_headers)
    assert summary_res.status_code == 200
    data = summary_res.json()

    # Must NOT report bleeding today!
    assert data["is_bleeding"] is False
    assert data["phase"] != "menstrual"
    assert data["days_until_next_period"] == 1


@pytest.mark.asyncio
async def test_cycle_duplicate_period_start_rejected_with_409(async_client: AsyncClient, auth_headers: dict):
    p_date = date(2025, 1, 10)
    # 1. Create first period
    r1 = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(p_date), "period_end": str(p_date + timedelta(days=4))},
    )
    assert r1.status_code == 201

    # 2. Attempt duplicate creation for same user on same period_start -> 409 Conflict
    r2 = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(p_date), "period_end": str(p_date + timedelta(days=5))},
    )
    assert r2.status_code in (409, 400)  # DB unique constraint or overlap check rejected with conflict


@pytest.mark.asyncio
async def test_end_current_cycle_endpoint(async_client: AsyncClient, other_user_auth_headers: dict):
    # 1. Initially no ongoing period -> 404
    r_fail = await async_client.post(
        "/api/v1/cycles/current/end",
        headers=other_user_auth_headers,
        json={},
    )
    assert r_fail.status_code == 404
    assert "No active ongoing period found" in r_fail.json()["detail"]

    # 2. Start ongoing period (start 3 days ago, period_end is None)
    start_date = date.today() - timedelta(days=3)
    r_start = await async_client.post(
        "/api/v1/cycles",
        headers=other_user_auth_headers,
        json={"period_start": str(start_date), "period_end": None},
    )
    assert r_start.status_code == 201

    # 3. Verify current cycle shows ongoing
    r_cur = await async_client.get("/api/v1/cycles/current", headers=other_user_auth_headers)
    assert r_cur.status_code == 200
    assert r_cur.json()["latest_period_end"] is None

    # 4. Call /current/end
    r_end = await async_client.post(
        "/api/v1/cycles/current/end",
        headers=other_user_auth_headers,
        json={"period_end": str(date.today())},
    )
    assert r_end.status_code == 200
    end_data = r_end.json()
    assert end_data["period_end"] == str(date.today())
    assert end_data["period_length_days"] == 4

    # 5. Verify current cycle now has latest_period_end set
    r_cur2 = await async_client.get("/api/v1/cycles/current", headers=other_user_auth_headers)
    assert r_cur2.status_code == 200
    assert r_cur2.json()["latest_period_end"] == str(date.today())

