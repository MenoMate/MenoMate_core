from datetime import date, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_onboarding_normal_flow(async_client: AsyncClient, auth_headers: dict):
    # NOTE: end uses date.today()-1 (not date.today()) because onboarding
    # enforces strict USER-LOCAL bounds (NULL timezone -> UTC fallback) while
    # date.today() is server-local; on machines ahead of UTC the two differ.
    start = date.today() - timedelta(days=3)
    end = date.today() - timedelta(days=1)
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
            "last_period_end": str(date.today() - timedelta(days=1)),
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
        "last_period_end": str(date.today() - timedelta(days=1)),
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


# ---------------------------------------------------------------------------
# PART A HARDENING (§3): completion contract, user-local bounds, one-time
# semantics, null handling, isolation. Dates are anchored with a 2-day past
# margin (never date.today() as an end) so they stay valid under the strict
# user-local bound on any machine timezone (see note in normal_flow above).
# ---------------------------------------------------------------------------

def _fresh_headers():
    import uuid
    from tests.conftest import make_token

    uid = uuid.uuid4()
    return uid, {"Authorization": f"Bearer {make_token(uid)}"}


def _valid_payload(start, end=None, **overrides):
    payload = {
        "name": "Hardening User",
        "last_period_start": str(start),
    }
    if end is not None:
        payload["last_period_end"] = str(end)
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_onboarding_rejects_null_name(async_client: AsyncClient):
    _, headers = _fresh_headers()
    payload = _valid_payload(date.today() - timedelta(days=5))
    del payload["name"]
    res = await async_client.post("/api/v1/onboarding/complete", headers=headers, json=payload)
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_rejects_empty_name(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() - timedelta(days=5), name=""),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_rejects_whitespace_name(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() - timedelta(days=5), name="   "),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_trims_name(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() - timedelta(days=5), name="  Maya  "),
    )
    assert res.status_code == 201
    assert res.json()["profile"]["name"] == "Maya"


@pytest.mark.asyncio
async def test_onboarding_rejects_future_start(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() + timedelta(days=10), name="Future Start"),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_rejects_tomorrow_start_user_local(async_client: AsyncClient):
    # Strict user-local bound: start == server tomorrow passes the coarse
    # schema guard, so the route-level user-local check must reject it.
    # (On machines behind UTC this coincides with the schema guard; the
    # frozen-clock boundary test below proves the user-local anchor.)
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() + timedelta(days=1), name="Tomorrow"),
    )
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_onboarding_rejects_future_end(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(
            date.today() - timedelta(days=3),
            date.today() + timedelta(days=5),
            name="Future End",
        ),
    )
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_onboarding_timezone_boundary(async_client: AsyncClient, monkeypatch):
    """User-local today (not server-local) is authoritative.

    Frozen instant 2026-06-01T05:00Z: UTC date is Jun 1, Pacific/Midway
    (UTC-11) is still May 31. A May-31 start with the Midway zone must be
    accepted; a Jun-1 start with the Midway zone is future and rejected —
    even though Jun 1 <= server/UTC today.
    """
    from datetime import datetime, timezone as dt_timezone

    import app.services.timezone as tz_module

    frozen = datetime(2026, 6, 1, 5, 0, tzinfo=dt_timezone.utc)
    monkeypatch.setattr(tz_module, "_utcnow", lambda: frozen)

    _, h1 = _fresh_headers()
    ok = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=h1,
        json=_valid_payload("2026-05-31", "2026-05-31",
                            name="Boundary OK", timezone="Pacific/Midway"),
    )
    assert ok.status_code == 201, ok.text

    _, h2 = _fresh_headers()
    future = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=h2,
        json=_valid_payload("2026-06-01", name="Boundary Future",
                            timezone="Pacific/Midway"),
    )
    assert future.status_code == 400, future.text


@pytest.mark.asyncio
async def test_onboarding_completed_period_accepted(async_client: AsyncClient):
    _, headers = _fresh_headers()
    start = date.today() - timedelta(days=6)
    end = date.today() - timedelta(days=2)
    res = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers, json=_valid_payload(start, end)
    )
    assert res.status_code == 201
    assert res.json()["period_end"] == str(end)


@pytest.mark.asyncio
async def test_onboarding_ongoing_period_accepted(async_client: AsyncClient):
    _, headers = _fresh_headers()
    start = date.today() - timedelta(days=2)
    res = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers, json=_valid_payload(start)
    )
    assert res.status_code == 201
    assert res.json()["period_end"] is None


@pytest.mark.asyncio
async def test_onboarding_rejects_inverted_dates(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(
            date.today() - timedelta(days=2), date.today() - timedelta(days=5)
        ),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_rejects_malformed_cycle_value(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() - timedelta(days=5), usual_cycle_days=99),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_accepts_valid_cycle_value(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() - timedelta(days=5), usual_cycle_days=28),
    )
    assert res.status_code == 201
    assert res.json()["profile"]["usual_cycle_days"] == 28


@pytest.mark.asyncio
async def test_onboarding_rejects_malformed_period_length(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() - timedelta(days=5), usual_period_days=99),
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_accepts_valid_period_length(async_client: AsyncClient):
    _, headers = _fresh_headers()
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json=_valid_payload(date.today() - timedelta(days=5), usual_period_days=5),
    )
    assert res.status_code == 201
    assert res.json()["profile"]["usual_period_days"] == 5


@pytest.mark.asyncio
async def test_onboarding_repeated_exact_same_safe(async_client: AsyncClient):
    _, headers = _fresh_headers()
    start = date(2026, 3, 1)
    payload = _valid_payload(start, date(2026, 3, 5),
                             usual_cycle_days=28, usual_period_days=5)
    r1 = await async_client.post("/api/v1/onboarding/complete", headers=headers, json=payload)
    assert r1.status_code == 201
    r2 = await async_client.post("/api/v1/onboarding/complete", headers=headers, json=payload)
    assert r2.status_code == 201
    assert r1.json()["period_id"] == r2.json()["period_id"]


@pytest.mark.asyncio
async def test_onboarding_repeat_ongoing_clears_end(async_client: AsyncClient):
    """Same-start repeat mirrors the stated period state: Ended -> Ongoing
    (explicit null end) must clear a previously stored end date."""
    _, headers = _fresh_headers()
    start = date(2026, 4, 1)
    r1 = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers,
        json=_valid_payload(start, date(2026, 4, 5)),
    )
    assert r1.status_code == 201
    assert r1.json()["period_end"] == "2026-04-05"
    r2 = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers,
        json=_valid_payload(start),
    )
    assert r2.status_code == 201
    assert r2.json()["period_id"] == r1.json()["period_id"]
    assert r2.json()["period_end"] is None


@pytest.mark.asyncio
async def test_onboarding_already_completed_rejected(async_client: AsyncClient):
    _, headers = _fresh_headers()
    r1 = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers,
        json=_valid_payload(date(2026, 5, 1), date(2026, 5, 5)),
    )
    assert r1.status_code == 201
    r2 = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers,
        json=_valid_payload(date(2026, 6, 10), date(2026, 6, 14)),
    )
    assert r2.status_code == 409
    assert "History" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_onboarding_already_completed_creates_no_cycle(
    async_client: AsyncClient, db_session: AsyncSession
):
    from sqlalchemy import func, select
    from app.models.cycle import Cycle

    uid, headers = _fresh_headers()
    r1 = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers,
        json=_valid_payload(date(2026, 5, 1), date(2026, 5, 5)),
    )
    assert r1.status_code == 201
    r2 = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers,
        json=_valid_payload(date(2026, 6, 10), date(2026, 6, 14)),
    )
    assert r2.status_code == 409
    count = await db_session.execute(
        select(func.count()).select_from(Cycle).where(Cycle.user_id == uid)
    )
    assert count.scalar_one() == 1


@pytest.mark.asyncio
async def test_onboarding_omitted_usuals_do_not_erase(async_client: AsyncClient):
    _, headers = _fresh_headers()
    start = date(2026, 7, 1)
    r1 = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers,
        json=_valid_payload(start, date(2026, 7, 5),
                             usual_cycle_days=30, usual_period_days=6),
    )
    assert r1.status_code == 201
    # Same-start repeat omitting usual_* must keep stored values
    # (_valid_payload omits usual_* unless passed: pure omission here).
    payload = _valid_payload(start, date(2026, 7, 5))
    assert "usual_cycle_days" not in payload
    r2 = await async_client.post("/api/v1/onboarding/complete", headers=headers, json=payload)
    assert r2.status_code == 201
    assert r2.json()["profile"]["usual_cycle_days"] == 30
    assert r2.json()["profile"]["usual_period_days"] == 6


@pytest.mark.asyncio
async def test_onboarding_user_isolation(
    async_client: AsyncClient, other_user_auth_headers: dict
):
    # User A onboards; user B with a different start is unaffected and
    # receives their own independent period (no cross-user 409/overlap).
    _, headers_a = _fresh_headers()
    ra = await async_client.post(
        "/api/v1/onboarding/complete", headers=headers_a,
        json=_valid_payload(date(2026, 8, 1), date(2026, 8, 5)),
    )
    assert ra.status_code == 201
    rb = await async_client.post(
        "/api/v1/onboarding/complete", headers=other_user_auth_headers,
        json=_valid_payload(date(2026, 8, 1), date(2026, 8, 5)),
    )
    assert rb.status_code == 201
    assert rb.json()["period_id"] != ra.json()["period_id"]
