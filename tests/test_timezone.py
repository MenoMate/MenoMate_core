"""Batch 2D-1: user-timezone-aware calendar-date semantics.

All boundary tests use FIXED instants (never the machine clock) via the
app.services.timezone._utcnow seam for route-level tests, or explicit
`today=` arguments for service-level tests. Production code never depends
on the test machine timezone.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.timezone as tzmod
from app.services.summary import get_current_cycle_summary
from app.services.timezone import user_today, validate_timezone

KOLKATA = "Asia/Kolkata"       # UTC+5:30, no DST (ahead)
NEW_YORK = "America/New_York"  # UTC-4/-5, no DST ambiguity here (behind)

# Frozen instants are derived from the REAL machine date so the coarse
# server-relative schema guard (+1 day) stays aligned with the app clock:
# - frozen_a: real-today 20:00 UTC -> Kolkata is always real-today+1
#   (01:30 next day; DST-free zone, always flips).
# - frozen_b: real-today 02:00 UTC -> New York is always real-today-1
#   (21:00/22:00 previous day for EST/EDT; always flips).
# Pure unit tests below still use fully fixed instants.
def _real_today() -> date:
    return date.today()


@pytest.fixture
def frozen_a(monkeypatch):
    instant = datetime.combine(_real_today(), datetime.min.time()).replace(
        hour=20, tzinfo=timezone.utc
    )
    monkeypatch.setattr(tzmod, "_utcnow", lambda: instant)


@pytest.fixture
def frozen_b(monkeypatch):
    instant = datetime.combine(_real_today(), datetime.min.time()).replace(
        hour=2, tzinfo=timezone.utc
    )
    monkeypatch.setattr(tzmod, "_utcnow", lambda: instant)


def _local_a() -> date:
    return _real_today() + timedelta(days=1)


def _local_b() -> date:
    return _real_today() - timedelta(days=1)


# Fully fixed instants for pure unit tests (no routes involved).
U_INSTANT = datetime(2026, 9, 13, 20, 0, tzinfo=timezone.utc)  # -> Kolkata 09-14
U_KOLKATA = date(2026, 9, 14)
V_INSTANT = datetime(2026, 9, 14, 2, 0, tzinfo=timezone.utc)  # -> NY 09-13
V_NY = date(2026, 9, 13)


async def _set_tz(async_client: AsyncClient, headers: dict, tz_name) -> None:
    res = await async_client.patch(
        "/api/v1/profile", headers=headers, json={"timezone": tz_name}
    )
    assert res.status_code == 200, res.text


# --- A/B. Unit: user-local date on both sides of UTC ------------------------

def test_user_today_ahead_of_utc():
    assert user_today(KOLKATA, U_INSTANT) == U_KOLKATA


def test_user_today_behind_utc():
    assert user_today(NEW_YORK, V_INSTANT) == V_NY


def test_user_today_invalid_and_missing_fallback():
    assert user_today("Not/AZone", U_INSTANT) == date(2026, 9, 13)
    assert user_today(None, U_INSTANT) == date(2026, 9, 13)
    assert user_today("   ", U_INSTANT) == date(2026, 9, 13)
    naive = datetime(2026, 9, 13, 20, 0)  # naive treated as UTC
    assert user_today(KOLKATA, naive) == U_KOLKATA


def test_validate_timezone():
    assert validate_timezone(KOLKATA) == KOLKATA
    assert validate_timezone("  America/New_York  ") == NEW_YORK
    assert validate_timezone(None) is None
    with pytest.raises(ValueError):
        validate_timezone("IST")
    with pytest.raises(ValueError):
        validate_timezone("+05:30")
    with pytest.raises(ValueError):
        validate_timezone("Moon/Olympus")
    with pytest.raises(ValueError):
        validate_timezone("   ")


# --- I/J. Profile timezone API ----------------------------------------------

@pytest.mark.asyncio
async def test_profile_timezone_roundtrip_and_validation(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["timezone"] is None  # legacy: unset

    await _set_tz(async_client, auth_headers, KOLKATA)
    res = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res.json()["timezone"] == KOLKATA

    # Update (travel) persists.
    await _set_tz(async_client, auth_headers, NEW_YORK)
    res = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res.json()["timezone"] == NEW_YORK

    # Invalid identifiers rejected, stored value untouched.
    for bad in ["IST", "+05:30", "Mars/Phobos", ""]:
        res = await async_client.patch(
            "/api/v1/profile", headers=auth_headers, json={"timezone": bad}
        )
        assert res.status_code == 422, bad
    res = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res.json()["timezone"] == NEW_YORK


@pytest.mark.asyncio
async def test_onboarding_persists_timezone(
    async_client: AsyncClient, other_user_auth_headers: dict
):
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=other_user_auth_headers,
        json={
            "name": "TZ",
            "last_period_start": "2026-09-01",
            "timezone": KOLKATA,
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["profile"]["timezone"] == KOLKATA


# --- A. Route: ahead-of-UTC user lives on local date -------------------------

@pytest.mark.asyncio
async def test_current_summary_uses_ahead_local_date(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    # Log a period starting on the USER's local today (server UTC: yesterday).
    local = _local_a()
    res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(local), "period_end": None},
    )
    assert res.status_code == 201, res.text
    res = await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    body = res.json()
    assert body["is_bleeding"] is True
    assert body["current_cycle_day"] == 1
    assert body["latest_period_start"] == str(local)


@pytest.mark.asyncio
async def test_retro_end_defaults_to_ahead_local_today(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    local = _local_a()
    res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(local - timedelta(days=2)), "period_end": None},
    )
    assert res.status_code == 201, res.text
    res = await async_client.post("/api/v1/cycles/current/end", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["period_end"] == str(local)  # not server UTC date


@pytest.mark.asyncio
async def test_logs_default_to_ahead_local_date(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    res = await async_client.post(
        "/api/v1/logs", headers=auth_headers, json={"pain": 3}
    )
    assert res.status_code == 200, res.text
    assert res.json()["log_date"] == str(_local_a())


# --- B. Route: behind-UTC user lives on local date ---------------------------

@pytest.mark.asyncio
async def test_current_summary_uses_behind_local_date(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict, frozen_b
):
    await _set_tz(async_client, auth_headers, NEW_YORK)
    # Local-today start (server UTC: tomorrow).
    local = _local_b()
    res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(local), "period_end": None},
    )
    assert res.status_code == 201, res.text
    res = await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    body = res.json()
    assert body["is_bleeding"] is True
    assert body["current_cycle_day"] == 1

    # Two days past the user's local today is rejected as a future start
    # by the route check (clean user: no ongoing-period interference).
    # It passes the coarse schema guard, proving the route check fires.
    await _set_tz(async_client, other_user_auth_headers, NEW_YORK)
    res = await async_client.post(
        "/api/v1/cycles",
        headers=other_user_auth_headers,
        json={"period_start": str(local + timedelta(days=2)), "period_end": None},
    )
    assert res.status_code == 400


# --- E. Explicit future end rejected against user-local today ----------------

@pytest.mark.asyncio
async def test_explicit_future_end_rejected(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    local = _local_a()
    res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(local - timedelta(days=2)), "period_end": None},
    )
    assert res.status_code == 201, res.text
    # Local today + 1 is in the future for this user.
    res = await async_client.post(
        "/api/v1/cycles/current/end",
        headers=auth_headers,
        json={"period_end": str(local + timedelta(days=1))},
    )
    assert res.status_code == 400
    # Local today itself is accepted.
    res = await async_client.post(
        "/api/v1/cycles/current/end",
        headers=auth_headers,
        json={"period_end": str(local)},
    )
    assert res.status_code == 200, res.text


# --- F/G. Explicit log dates preserved exactly --------------------------------

@pytest.mark.asyncio
async def test_explicit_log_dates_untouched(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    past = _local_a() - timedelta(days=4)
    res = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"pain": 5, "log_date": str(past)},
    )
    assert res.status_code == 200, res.text
    assert res.json()["log_date"] == str(past)
    res = await async_client.get(
        f"/api/v1/logs/{past}", headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["log_date"] == str(past)


# --- C/D/H. Status mechanics under explicit today (algorithm untouched) -------

@pytest.mark.asyncio
async def test_prediction_status_and_countdown_under_explicit_today(
    db_session: AsyncSession,
):
    from app.models.cycle import Cycle
    from tests.conftest import TEST_USER_ID

    base = date(2026, 8, 1)
    # Three observed 28-day intervals -> robust prediction of 28d.
    for i in range(4):
        db_session.add(
            Cycle(
                user_id=TEST_USER_ID,
                period_start=base + timedelta(days=28 * i),
                period_end=base + timedelta(days=28 * i + 4),
            )
        )
    await db_session.commit()

    # Last start Oct 24 + predicted length 28 -> next expected Nov 21.
    predicted = base + timedelta(days=28 * 4)
    assert predicted == date(2026, 11, 21)

    summary = await get_current_cycle_summary(
        db_session, TEST_USER_ID, today=predicted
    )
    assert summary["prediction_status"] == "today"
    assert summary["days_until_next_period"] == 0

    summary = await get_current_cycle_summary(
        db_session, TEST_USER_ID, today=predicted - timedelta(days=1)
    )
    assert summary["prediction_status"] == "upcoming"
    assert summary["days_until_next_period"] == 1

    summary = await get_current_cycle_summary(
        db_session, TEST_USER_ID, today=predicted + timedelta(days=5)
    )
    assert summary["prediction_status"] == "awaiting_next_start"
    assert summary["days_until_next_period"] == 0


@pytest.mark.asyncio
async def test_local_midnight_boundary_status(
    db_session: AsyncSession,
):
    """Same served prediction, two user-local dates straddling midnight."""
    from app.models.cycle import Cycle
    from tests.conftest import TEST_USER_ID

    base = date(2026, 8, 1)
    for i in range(4):
        db_session.add(
            Cycle(
                user_id=TEST_USER_ID,
                period_start=base + timedelta(days=28 * i),
                period_end=base + timedelta(days=28 * i + 4),
            )
        )
    await db_session.commit()
    predicted = base + timedelta(days=28 * 4)  # 2026-11-21

    eve = await get_current_cycle_summary(
        db_session, TEST_USER_ID, today=predicted - timedelta(days=1)
    )
    assert (eve["prediction_status"], eve["days_until_next_period"]) == (
        "upcoming",
        1,
    )
    midnight = await get_current_cycle_summary(
        db_session, TEST_USER_ID, today=predicted
    )
    assert (midnight["prediction_status"], midnight["days_until_next_period"]) == (
        "today",
        0,
    )


# --- I. Missing timezone falls back without breaking --------------------------

@pytest.mark.asyncio
async def test_missing_timezone_fallback(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    # No timezone set: legacy UTC-date behavior, requests still succeed.
    server_today = _real_today()
    res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(server_today), "period_end": None},
    )
    assert res.status_code == 201, res.text
    res = await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    assert res.json()["is_bleeding"] is True


# --- Therapy recommend picks up the user-local log ----------------------------

@pytest.mark.asyncio
async def test_therapy_recommend_uses_local_today_log(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    local = _local_a()
    res = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"pain": 7, "log_date": str(local)},
    )
    assert res.status_code == 200, res.text
    res = await async_client.post(
        "/api/v1/therapy/recommend", headers=auth_headers, json={}
    )
    assert res.status_code == 200, res.text
    # Proves the user-local log (09-14) was picked up: server-local 09-13
    # has no log, which would yield pain_score 0.
    assert res.json()["pain_score"] == 7
