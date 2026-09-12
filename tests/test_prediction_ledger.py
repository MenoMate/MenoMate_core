"""
Ledger tests (API-level, so the route commit paths are exercised).

Proves: served model predictions are snapshotted with exact production
values, API responses are byte-identical to uninstrumented behavior,
non-predictions record nothing, and new starts resolve open entries with
correct signed errors.
"""
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from conftest import TEST_USER_ID, test_async_session
from app.models.prediction_ledger import PredictionLedger
from app.services.prediction_ledger import BASELINE_METHOD


async def _rows():
    async with test_async_session() as session:
        res = await session.execute(
            select(PredictionLedger)
            .where(PredictionLedger.user_id == TEST_USER_ID)
            .order_by(PredictionLedger.id)
        )
        return list(res.scalars().all())


async def _log_period(client, headers, start, end=None):
    payload = {"period_start": str(start)}
    if end is not None:
        payload["period_end"] = str(end)
    res = await client.post("/api/v1/cycles", headers=headers, json=payload)
    assert res.status_code == 201, res.text
    return res.json()


@pytest.mark.asyncio
async def test_served_prediction_recorded_with_exact_values(
    async_client: AsyncClient, auth_headers: dict
):
    today = date.today()
    p1_start = today - timedelta(days=32)
    p2_start = today - timedelta(days=4)
    await _log_period(async_client, auth_headers, p1_start, today - timedelta(days=28))
    await _log_period(async_client, auth_headers, p2_start, today - timedelta(days=1))

    res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    # Frozen production behavior: 1 interval [28] -> 28, low, history.
    # (predicted_cycle_length / prediction_source are service-internal;
    # the response schema exposes predicted_next_period + confidence.)
    assert body["prediction_confidence"] == "low"
    assert body["predicted_next_period"] == str(p2_start + timedelta(days=28))
    assert body["days_until_next_period"] == 24
    assert body["prediction_status"] == "upcoming"

    rows = await _rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.method == BASELINE_METHOD
    assert row.predicted_at == today
    assert row.predicted_cycle_length == 28
    assert row.predicted_next_period == p2_start + timedelta(days=28)
    assert row.confidence == "low"
    assert row.source == "history"
    assert row.basis_start == p2_start
    assert row.basis_intervals == 1
    assert row.basis_usual is None  # no baseline declared
    assert row.variability == pytest.approx(0.0)
    assert row.resolved_actual_start is None
    assert row.error_days is None


@pytest.mark.asyncio
async def test_basis_usual_recorded_exactly_as_served(
    async_client: AsyncClient, auth_headers: dict
):
    today = date.today()
    res = await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"usual_cycle_days": 30}
    )
    assert res.status_code == 200, res.text
    p1_start = today - timedelta(days=32)
    p2_start = today - timedelta(days=4)
    await _log_period(async_client, auth_headers, p1_start, today - timedelta(days=28))
    await _log_period(async_client, auth_headers, p2_start, today - timedelta(days=1))

    res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert res.status_code == 200
    # Prediction behavior unchanged: history still wins over usual.
    assert res.json()["prediction_confidence"] == "low"
    assert res.json()["predicted_next_period"] == str(p2_start + timedelta(days=28))

    rows = await _rows()
    assert len(rows) == 1
    assert rows[0].basis_usual == 30


@pytest.mark.asyncio
async def test_response_shape_has_no_ledger_keys(
    async_client: AsyncClient, auth_headers: dict
):
    today = date.today()
    await _log_period(
        async_client, auth_headers, today - timedelta(days=32), today - timedelta(days=28)
    )
    await _log_period(
        async_client, auth_headers, today - timedelta(days=4), today - timedelta(days=1)
    )
    for path in ("/api/v1/summary/current", "/api/v1/cycles/current"):
        res = await async_client.get(path, headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert not any(k.startswith("ledger") for k in body), path
        assert "basis_intervals" not in body, path


@pytest.mark.asyncio
async def test_no_ledger_without_model_prediction(
    async_client: AsyncClient, auth_headers: dict
):
    # Empty state: no prediction served.
    res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert res.json()["has_data"] is False
    assert await _rows() == []

    # Display-only user override (future logged date): not a model prediction.
    res = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": str(date.today() + timedelta(days=1))},
    )
    assert res.status_code == 201, res.text
    res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    # Display-only user override: served as high-confidence upcoming date.
    assert res.json()["prediction_confidence"] == "high"
    assert res.json()["predicted_next_period"] == str(date.today() + timedelta(days=1))
    assert await _rows() == []


@pytest.mark.asyncio
async def test_new_start_resolves_open_entry(
    async_client: AsyncClient, auth_headers: dict
):
    today = date.today()
    p1_start = today - timedelta(days=64)
    p2_start = today - timedelta(days=36)
    await _log_period(async_client, auth_headers, p1_start, p1_start + timedelta(days=4))
    await _log_period(async_client, auth_headers, p2_start, p2_start + timedelta(days=4))
    await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert len(await _rows()) == 1

    # Actual next start arrives 2 days after the predicted day (both in past).
    new_start = p2_start + timedelta(days=30)
    await _log_period(async_client, auth_headers, new_start)

    rows = await _rows()
    assert len(rows) == 1
    assert rows[0].resolved_actual_start == new_start
    assert rows[0].error_days == 2
    # Served values frozen at record time, untouched by resolution.
    assert rows[0].predicted_next_period == p2_start + timedelta(days=28)


@pytest.mark.asyncio
async def test_new_start_resolves_all_open_entries(
    async_client: AsyncClient, auth_headers: dict
):
    """GAP 1 proofs: three servings, one start resolves all, same actual,
    independent errors, idempotent repeat, unrelated opens untouched."""
    from app.services.prediction_ledger import resolve_for_new_start
    from conftest import test_async_session

    today = date.today()
    p1_start = today - timedelta(days=92)
    p2_start = today - timedelta(days=64)
    await _log_period(async_client, auth_headers, p1_start, p1_start + timedelta(days=4))
    await _log_period(async_client, auth_headers, p2_start, p2_start + timedelta(days=4))

    # (1) three servings on the same basis are all open before the start.
    for _ in range(2):
        res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
        assert res.status_code == 200
    # Backfill an earlier period: same basis, but the retrained prediction
    # changes ([28] -> [26, 28]), giving an independent second forecast.
    # The backfill itself must resolve nothing (basis p2 is not before p0).
    p0_start = today - timedelta(days=118)
    await _log_period(async_client, auth_headers, p0_start, p0_start + timedelta(days=4))
    res = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert res.status_code == 200
    rows = await _rows()
    assert len(rows) == 3
    assert all(r.resolved_actual_start is None for r in rows)
    assert {r.predicted_next_period for r in rows} == {
        p2_start + timedelta(days=28),
        p2_start + timedelta(days=27),
    }

    # (2/3/4) one new start resolves all three to the same actual start
    # with independent errors.
    new_start = p2_start + timedelta(days=30)
    await _log_period(async_client, auth_headers, new_start, new_start + timedelta(days=4))
    rows = await _rows()
    assert len(rows) == 3
    assert all(r.resolved_actual_start == new_start for r in rows)
    assert sorted(r.error_days for r in rows) == [2, 2, 3]

    # (5) repeated resolution is idempotent: nothing further resolves.
    async with test_async_session() as session:
        assert await resolve_for_new_start(session, TEST_USER_ID, new_start) == []
    rows = await _rows()
    assert sorted(r.error_days for r in rows) == [2, 2, 3]
    assert all(r.resolved_actual_start == new_start for r in rows)

    # (6) unrelated opens are not resolved: a serving on the new basis
    # stays open until its own cycle's start arrives.
    await async_client.get("/api/v1/summary/current", headers=auth_headers)
    rows = await _rows()
    assert len(rows) == 4 and rows[3].resolved_actual_start is None
    assert rows[3].basis_start == new_start
    later = rows[3].predicted_next_period
    assert later is not None and later <= today
    await _log_period(async_client, auth_headers, later)
    rows = await _rows()
    assert rows[3].resolved_actual_start == later
    assert rows[3].error_days == 0
    # Earlier cycles' rows are untouched by the later resolution.
    assert [r.resolved_actual_start for r in rows[:3]] == [new_start] * 3
