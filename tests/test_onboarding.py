from datetime import date, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


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


@pytest.mark.asyncio
async def test_onboarding_cycle_validation_parity_and_overlap(async_client: AsyncClient, auth_headers: dict):
    # 1. period_end before period_start -> 422
    res_inverted = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=auth_headers,
        json={
            "name": "Validation Test",
            "last_period_start": str(date.today() - timedelta(days=5)),
            "last_period_end": str(date.today() - timedelta(days=7)),
        },
    )
    assert res_inverted.status_code == 422

    # 2. duration > 30 days -> 422
    res_too_long = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=auth_headers,
        json={
            "name": "Validation Test",
            "last_period_start": str(date.today() - timedelta(days=40)),
            "last_period_end": str(date.today() - timedelta(days=5)),
        },
    )
    assert res_too_long.status_code == 422

    # 3. future period_start (> tomorrow) -> 422
    res_future = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=auth_headers,
        json={
            "name": "Validation Test",
            "last_period_start": str(date.today() + timedelta(days=10)),
        },
    )
    assert res_future.status_code == 422

    # 4. Overlapping periods with existing period -> 400
    # First create a cycle directly
    c_start = date(2026, 7, 1)
    c_end = date(2026, 7, 5)
    create_cycle = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(c_start), "period_end": str(c_end)},
    )
    assert create_cycle.status_code == 201

    # Attempt onboarding with overlapping period range
    res_overlap = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=auth_headers,
        json={
            "name": "Validation Test",
            "last_period_start": str(date(2026, 7, 3)),
            "last_period_end": str(date(2026, 7, 8)),
        },
    )
    assert res_overlap.status_code == 400
    assert "overlaps with existing period" in res_overlap.json()["detail"]


@pytest.mark.asyncio
async def test_onboarding_atomic_rollback_on_failure(
    async_client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """
    Verifies that if onboarding fails during cycle validation,
    the staged profile is rolled back and NOT left behind in the database.
    """
    import uuid
    from fastapi import HTTPException
    from sqlalchemy import select
    from app.models.profile import Profile
    from tests.conftest import make_token
    import app.api.v1.onboarding as ob_module

    fresh_uid = uuid.uuid4()
    headers = {"Authorization": f"Bearer {make_token(fresh_uid)}"}

    # Confirm no profile exists in database
    p_check = await db_session.execute(select(Profile).where(Profile.user_id == fresh_uid))
    assert p_check.scalar_one_or_none() is None

    # Simulate cycle validation failure inside complete_onboarding
    async def mock_fail_check(*args, **kwargs):
        raise HTTPException(status_code=400, detail="Simulated cycle validation failure")

    monkeypatch.setattr(ob_module, "check_cycle_overlap", mock_fail_check)

    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json={
            "name": "Atomic Rollback User",
            "last_period_start": str(date.today() - timedelta(days=3)),
            "last_period_end": str(date.today()),
            "usual_cycle_days": 28,
            "usual_period_days": 5,
        },
    )
    assert res.status_code == 400
    assert "Simulated cycle validation failure" in res.json()["detail"]

    # Verify profile was rolled back and is NOT present in database
    p_after = await db_session.execute(select(Profile).where(Profile.user_id == fresh_uid))
    assert p_after.scalar_one_or_none() is None, "Failed onboarding left an orphaned profile record!"


@pytest.mark.asyncio
async def test_onboarding_concurrent_requests_safe(
    async_client: AsyncClient, db_session: AsyncSession
):
    """
    Verifies that concurrent onboarding requests for the same new user
    complete safely without unhandled conflicts or orphaned records.
    """
    import asyncio
    import uuid
    from sqlalchemy import select
    from app.models.profile import Profile
    from tests.conftest import make_token

    fresh_uid = uuid.uuid4()
    headers = {"Authorization": f"Bearer {make_token(fresh_uid)}"}

    payload = {
        "name": "Concurrent User",
        "last_period_start": str(date.today() - timedelta(days=2)),
        "last_period_end": str(date.today()),
        "usual_cycle_days": 30,
        "usual_period_days": 5,
    }

    # Execute 3 concurrent onboarding requests for the exact same new user
    responses = await asyncio.gather(
        async_client.post("/api/v1/onboarding/complete", headers=headers, json=payload),
        async_client.post("/api/v1/onboarding/complete", headers=headers, json=payload),
        async_client.post("/api/v1/onboarding/complete", headers=headers, json=payload),
        return_exceptions=True,
    )

    for r in responses:
        assert not isinstance(r, Exception)
        assert r.status_code == 201
        assert r.json()["message"] == "Onboarding completed successfully."

    # Exactly one profile record should exist
    prof_stmt = select(Profile).where(Profile.user_id == fresh_uid)
    res = await db_session.execute(prof_stmt)
    profiles = res.scalars().all()
    assert len(profiles) == 1
