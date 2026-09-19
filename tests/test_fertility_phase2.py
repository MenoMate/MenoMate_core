"""Phase 2: fertility observations + evidence-gated ovulation/fertile-window engine.

Covers: observation validation, user isolation, engine states, fertile-window
safety wording, and regression proofs that the frozen period predictor,
timezone service, and Health Context behavior are untouched.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.timezone as tzmod
from app.services.fertility_estimator import (
    ALLOWED_STATUSES,
    ObservationEvidence,
    compute_fertility_estimate,
)
from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID

KOLKATA = "Asia/Kolkata"
NEW_YORK = "America/New_York"


def _real_today() -> date:
    return date.today()


@pytest.fixture
def frozen_b(monkeypatch):
    instant = datetime.combine(_real_today(), datetime.min.time()).replace(
        hour=2, tzinfo=timezone.utc
    )
    monkeypatch.setattr(tzmod, "_utcnow", lambda: instant)


@pytest.fixture
def frozen_a(monkeypatch):
    instant = datetime.combine(_real_today(), datetime.min.time()).replace(
        hour=20, tzinfo=timezone.utc
    )
    monkeypatch.setattr(tzmod, "_utcnow", lambda: instant)


async def _set_tz(async_client: AsyncClient, headers: dict, tz_name: str) -> None:
    res = await async_client.patch(
        "/api/v1/profile", headers=headers, json={"timezone": tz_name}
    )
    assert res.status_code == 200, res.text


async def _post_obs(async_client, headers, payload):
    return await async_client.post(
        "/api/v1/reproductive/observations", headers=headers, json=payload
    )


async def _make_periods(async_client, headers, starts):
    for s in starts:
        r = await async_client.post(
            "/api/v1/cycles",
            headers=headers,
            json={
                "period_start": str(s),
                "period_end": str(s + timedelta(days=4)),
            },
        )
        assert r.status_code == 201, r.text


def _stable_history():
    # Three observed 28-day intervals -> reused predictor confidence moderate.
    t = _real_today()
    return [t - timedelta(days=90), t - timedelta(days=62), t - timedelta(days=34), t - timedelta(days=6)]


# --- A. Observation model/schema --------------------------------------------


@pytest.mark.asyncio
async def test_create_valid_lh_observation(async_client: AsyncClient, auth_headers: dict):
    day = _real_today() - timedelta(days=3)
    res = await _post_obs(
        async_client,
        auth_headers,
        {"observation_date": str(day), "observation_type": "lh_test", "lh_result": "positive"},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["observation_date"] == str(day)
    assert body["observation_type"] == "lh_test"
    assert body["lh_result"] == "positive"
    assert body["bbt_celsius"] is None
    assert body["mucus_category"] is None
    assert body["user_id"] == str(TEST_USER_ID)
    assert body["source"] == "manual"


@pytest.mark.asyncio
async def test_create_valid_bbt_preserves_precision(async_client: AsyncClient, auth_headers: dict):
    day = _real_today() - timedelta(days=2)
    res = await _post_obs(
        async_client,
        auth_headers,
        {"observation_date": str(day), "observation_type": "bbt", "bbt_celsius": 36.65},
    )
    assert res.status_code == 201, res.text
    assert res.json()["bbt_celsius"] == 36.65


@pytest.mark.asyncio
async def test_create_valid_mucus_observation(async_client: AsyncClient, auth_headers: dict):
    day = _real_today() - timedelta(days=1)
    res = await _post_obs(
        async_client,
        auth_headers,
        {"observation_date": str(day), "observation_type": "cervical_mucus", "mucus_category": "egg_white"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["mucus_category"] == "egg_white"


@pytest.mark.asyncio
async def test_observation_type_enums_rejected(async_client: AsyncClient, auth_headers: dict):
    day = str(_real_today() - timedelta(days=1))
    for payload in (
        {"observation_date": day, "observation_type": "nope", "lh_result": "positive"},
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "faint_line"},
        {"observation_date": day, "observation_type": "cervical_mucus", "mucus_category": "spinnbart"},
        {"observation_date": day, "observation_type": "bbt", "bbt_celsius": 45.0},
        {"observation_date": day, "observation_type": "bbt", "bbt_celsius": 34.0},
    ):
        res = await _post_obs(async_client, auth_headers, payload)
        assert res.status_code == 422, payload


@pytest.mark.asyncio
async def test_exactly_one_value_column_enforced(async_client: AsyncClient, auth_headers: dict):
    day = str(_real_today() - timedelta(days=1))
    bad = [
        {"observation_date": day, "observation_type": "lh_test"},
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "positive", "bbt_celsius": 36.6},
        {"observation_date": day, "observation_type": "bbt"},
        {"observation_date": day, "observation_type": "bbt", "bbt_celsius": 36.6, "mucus_category": "dry"},
        {"observation_date": day, "observation_type": "cervical_mucus"},
        {"observation_date": day, "observation_type": "cervical_mucus", "lh_result": "negative", "mucus_category": "dry"},
    ]
    for payload in bad:
        res = await _post_obs(async_client, auth_headers, payload)
        assert res.status_code == 422, payload


@pytest.mark.asyncio
async def test_far_future_observation_rejected(async_client: AsyncClient, auth_headers: dict):
    res = await _post_obs(
        async_client,
        auth_headers,
        {
            "observation_date": str(_real_today() + timedelta(days=30)),
            "observation_type": "lh_test",
            "lh_result": "negative",
        },
    )
    assert res.status_code in (400, 422)


@pytest.mark.asyncio
async def test_future_observation_rejected_against_user_local_today(
    async_client: AsyncClient, auth_headers: dict, frozen_b
):
    await _set_tz(async_client, auth_headers, NEW_YORK)
    # Server-UTC today is tomorrow for this user: a biological observation
    # dated "today" (server) is in this user's future and must be rejected.
    res = await _post_obs(
        async_client,
        auth_headers,
        {
            "observation_date": str(_real_today()),
            "observation_type": "bbt",
            "bbt_celsius": 36.6,
        },
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_omitted_date_defaults_to_user_local_today(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    local = _real_today() + timedelta(days=1)
    res = await _post_obs(
        async_client, auth_headers, {"observation_type": "lh_test", "lh_result": "negative"}
    )
    assert res.status_code == 201, res.text
    assert res.json()["observation_date"] == str(local)


@pytest.mark.asyncio
async def test_upsert_same_day_type_overwrites(async_client: AsyncClient, auth_headers: dict):
    day = str(_real_today() - timedelta(days=4))
    first = await _post_obs(
        async_client, auth_headers,
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "negative"},
    )
    assert first.status_code == 201
    second = await _post_obs(
        async_client, auth_headers,
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "positive"},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["lh_result"] == "positive"
    listed = await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)
    assert len(listed.json()) == 1


@pytest.mark.asyncio
async def test_list_range_and_type_filter(async_client: AsyncClient, auth_headers: dict):
    t = _real_today()
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=5)), "observation_type": "lh_test", "lh_result": "negative"})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=3)), "observation_type": "bbt", "bbt_celsius": 36.5})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=1)), "observation_type": "cervical_mucus", "mucus_category": "creamy"})
    res = await async_client.get(
        "/api/v1/reproductive/observations",
        headers=auth_headers,
        params={"start_date": str(t - timedelta(days=4)), "end_date": str(t)},
    )
    assert res.status_code == 200
    assert len(res.json()) == 2
    # Newest-first ordering.
    assert res.json()[0]["observation_date"] >= res.json()[1]["observation_date"]
    res = await async_client.get(
        "/api/v1/reproductive/observations",
        headers=auth_headers,
        params={"observation_type": "bbt"},
    )
    assert len(res.json()) == 1
    res = await async_client.get(
        "/api/v1/reproductive/observations",
        headers=auth_headers,
        params={"start_date": str(t), "end_date": str(t - timedelta(days=1))},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_patch_note_clearing_and_type_immutability(async_client: AsyncClient, auth_headers: dict):
    day = str(_real_today() - timedelta(days=2))
    created = await _post_obs(
        async_client, auth_headers,
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "positive", "note": "evening"},
    )
    obs_id = created.json()["id"]
    # Explicit-null clears the note.
    patched = await async_client.patch(
        f"/api/v1/reproductive/observations/{obs_id}", headers=auth_headers, json={"note": None}
    )
    assert patched.status_code == 200
    assert patched.json()["note"] is None
    # Value columns of another type are rejected (no LH -> BBT morphing).
    morphed = await async_client.patch(
        f"/api/v1/reproductive/observations/{obs_id}", headers=auth_headers, json={"bbt_celsius": 36.7}
    )
    assert morphed.status_code == 422


@pytest.mark.asyncio
async def test_patch_date_move_conflict(async_client: AsyncClient, auth_headers: dict):
    t = _real_today()
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=6)), "observation_type": "bbt", "bbt_celsius": 36.4})
    second = await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=5)), "observation_type": "bbt", "bbt_celsius": 36.6})
    clash = await async_client.patch(
        f"/api/v1/reproductive/observations/{second.json()['id']}",
        headers=auth_headers,
        json={"observation_date": str(t - timedelta(days=6))},
    )
    assert clash.status_code == 409


@pytest.mark.asyncio
async def test_delete_observation(async_client: AsyncClient, auth_headers: dict):
    day = str(_real_today() - timedelta(days=2))
    created = await _post_obs(
        async_client, auth_headers,
        {"observation_date": day, "observation_type": "cervical_mucus", "mucus_category": "dry"},
    )
    obs_id = created.json()["id"]
    deleted = await async_client.delete(
        f"/api/v1/reproductive/observations/{obs_id}", headers=auth_headers
    )
    assert deleted.status_code == 204
    listed = await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)
    assert listed.json() == []


@pytest.mark.asyncio
async def test_mucus_scale_independent_from_daily_log_discharge(
    async_client: AsyncClient, auth_headers: dict
):
    day = _real_today() - timedelta(days=2)
    log = await async_client.post(
        "/api/v1/logs", headers=auth_headers, json={"log_date": str(day), "pain": 1, "discharge": "slippery"}
    )
    assert log.status_code == 200
    assert log.json()["discharge"] == "slippery"
    obs = await _post_obs(
        async_client, auth_headers,
        {"observation_date": str(day), "observation_type": "cervical_mucus", "mucus_category": "egg_white"},
    )
    assert obs.status_code == 201
    assert obs.json()["mucus_category"] == "egg_white"
    # Neither record disturbs the other.
    reread = await async_client.get(f"/api/v1/logs/{day}", headers=auth_headers)
    assert reread.json()["discharge"] == "slippery"


# --- B. Authorization -------------------------------------------------------


@pytest.mark.asyncio
async def test_reproductive_routes_require_auth(async_client: AsyncClient):
    assert (await async_client.get("/api/v1/reproductive/observations")).status_code == 401
    assert (await async_client.post("/api/v1/reproductive/observations", json={})).status_code in (401, 403)
    assert (await async_client.patch("/api/v1/reproductive/observations/1", json={})).status_code in (401, 403)
    assert (await async_client.delete("/api/v1/reproductive/observations/1")).status_code in (401, 403)
    assert (await async_client.get("/api/v1/reproductive/estimates")).status_code == 401


@pytest.mark.asyncio
async def test_cross_user_observation_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    day = str(_real_today() - timedelta(days=2))
    created = await _post_obs(
        async_client, auth_headers,
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "positive"},
    )
    obs_id = created.json()["id"]
    # Another user sees an empty list, never the row.
    listed = await async_client.get("/api/v1/reproductive/observations", headers=other_user_auth_headers)
    assert listed.status_code == 200
    assert listed.json() == []
    # Cross-user mutation by id is 404 (no existence oracle).
    assert (await async_client.patch(
        f"/api/v1/reproductive/observations/{obs_id}", headers=other_user_auth_headers, json={"note": "x"}
    )).status_code == 404
    assert (await async_client.delete(
        f"/api/v1/reproductive/observations/{obs_id}", headers=other_user_auth_headers
    )).status_code == 404
    # The other user's estimate reflects only their own (empty) evidence.
    est = await async_client.get("/api/v1/reproductive/estimates", headers=other_user_auth_headers)
    assert est.json()["status"] == "INSUFFICIENT_DATA"
    # Owner still owns the row.
    own = await async_client.patch(
        f"/api/v1/reproductive/observations/{obs_id}", headers=auth_headers, json={"note": "mine"}
    )
    assert own.status_code == 200


@pytest.mark.asyncio
async def test_client_supplied_user_id_is_ignored(async_client: AsyncClient, auth_headers: dict):
    day = str(_real_today() - timedelta(days=2))
    res = await _post_obs(
        async_client, auth_headers,
        {
            "observation_date": day,
            "observation_type": "bbt",
            "bbt_celsius": 36.6,
            "user_id": str(ANOTHER_USER_ID),
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["user_id"] == str(TEST_USER_ID)


@pytest.mark.asyncio
async def test_profile_delete_cascades_observations(
    async_client: AsyncClient, auth_headers: dict
):
    day = str(_real_today() - timedelta(days=2))
    created = await _post_obs(
        async_client, auth_headers,
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "negative"},
    )
    obs_id = created.json()["id"]
    deleted = await async_client.delete("/api/v1/profile", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)).json() == []
    assert (await async_client.patch(
        f"/api/v1/reproductive/observations/{obs_id}", headers=auth_headers, json={"note": "x"}
    )).status_code == 404


# --- C. Fertility engine ----------------------------------------------------


@pytest.mark.asyncio
async def test_estimate_insufficient_for_fresh_user(
    async_client: AsyncClient, other_user_auth_headers: dict
):
    res = await async_client.get("/api/v1/reproductive/estimates", headers=other_user_auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "INSUFFICIENT_DATA"
    assert body["estimated_ovulation_date"] is None
    assert body["fertile_window_start"] is None
    assert body["fertile_window_end"] is None
    assert body["evidence_source"] == "ESTIMATED"
    assert body["method"] == "fertility_v1"
    assert body["method_version"] == "1.0.0"
    assert body["evidence"]["evidence_schema_version"] == 1
    assert set(body.keys()) >= {
        "estimate_date", "status", "evidence_source", "evidence",
        "method", "method_version", "calculated_at", "timezone_name", "disclaimer",
    }


@pytest.mark.asyncio
async def test_no_usual_cycle_fallback_for_fertility(async_client: AsyncClient, auth_headers: dict):
    patched = await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"usual_cycle_days": 28}
    )
    assert patched.status_code == 200
    res = await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    body = res.json()
    # A stated 28-day usual must not fabricate a dated fertility estimate.
    assert body["status"] == "INSUFFICIENT_DATA"
    assert body["estimated_ovulation_date"] is None
    assert body["evidence"]["predicted_cycle_length"] is None


@pytest.mark.asyncio
async def test_history_without_biomarker_is_low_confidence(async_client: AsyncClient, auth_headers: dict):
    await _make_periods(async_client, auth_headers, _stable_history())
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    assert body["status"] == "LOW_CONFIDENCE"
    assert body["estimated_ovulation_date"] is None
    assert body["fertile_window_start"] is None
    assert body["fertile_window_end"] is None
    assert body["evidence"]["cycle_intervals_used"] == 3
    assert body["evidence"]["biomarker_types_present"] == []


@pytest.mark.asyncio
async def test_biomarker_without_history_is_low_confidence(async_client: AsyncClient, auth_headers: dict):
    day = str(_real_today() - timedelta(days=1))
    await _post_obs(async_client, auth_headers, {"observation_date": day, "observation_type": "lh_test", "lh_result": "positive"})
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    assert body["status"] == "LOW_CONFIDENCE"
    assert body["estimated_ovulation_date"] is None


@pytest.mark.asyncio
async def test_bbt_alone_never_drives_prospective_window(async_client: AsyncClient, auth_headers: dict):
    await _make_periods(async_client, auth_headers, _stable_history())
    t = _real_today()
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=3)), "observation_type": "bbt", "bbt_celsius": 36.8})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=2)), "observation_type": "bbt", "bbt_celsius": 37.0})
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    # BBT is retrospective: counted as evidence, never sufficient for a dated window.
    assert body["status"] == "LOW_CONFIDENCE"
    assert body["estimated_ovulation_date"] is None
    assert body["evidence"]["bbt_points"] == 2


@pytest.mark.asyncio
async def test_mucus_or_negative_lh_alone_is_low_confidence(async_client: AsyncClient, auth_headers: dict):
    await _make_periods(async_client, auth_headers, _stable_history())
    t = _real_today()
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=3)), "observation_type": "cervical_mucus", "mucus_category": "egg_white"})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=2)), "observation_type": "lh_test", "lh_result": "negative"})
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    assert body["status"] == "LOW_CONFIDENCE"
    assert body["estimated_ovulation_date"] is None
    assert body["evidence"]["mucus_observations"] == 1


@pytest.mark.asyncio
async def test_available_with_history_and_lh_anchor(async_client: AsyncClient, auth_headers: dict):
    starts = _stable_history()
    await _make_periods(async_client, auth_headers, starts)
    t = _real_today()
    lh_day = t - timedelta(days=3)
    await _post_obs(async_client, auth_headers, {"observation_date": str(lh_day), "observation_type": "lh_test", "lh_result": "positive"})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=2)), "observation_type": "bbt", "bbt_celsius": 36.6})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=1)), "observation_type": "cervical_mucus", "mucus_category": "watery"})
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    assert body["status"] == "AVAILABLE"
    assert body["evidence_source"] == "OBSERVED"
    predicted_next = starts[-1] + timedelta(days=28)
    ovulation = predicted_next - timedelta(days=14)
    assert body["estimated_ovulation_date"] == str(ovulation)
    assert body["fertile_window_start"] == str(ovulation - timedelta(days=5))
    assert body["fertile_window_end"] == str(ovulation + timedelta(days=1))
    assert str(lh_day) in body["evidence"]["lh_positive_dates"]
    assert body["evidence"]["bbt_points"] == 1
    assert body["evidence"]["mucus_observations"] == 1
    assert body["evidence"]["cycle_intervals_used"] == 3
    assert body["evidence"]["predicted_cycle_length"] == 28


@pytest.mark.asyncio
async def test_recalculation_after_observation_removal(async_client: AsyncClient, auth_headers: dict):
    await _make_periods(async_client, auth_headers, _stable_history())
    day = str(_real_today() - timedelta(days=3))
    created = await _post_obs(
        async_client, auth_headers,
        {"observation_date": day, "observation_type": "lh_test", "lh_result": "positive"},
    )
    assert (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()["status"] == "AVAILABLE"
    assert (await async_client.delete(
        f"/api/v1/reproductive/observations/{created.json()['id']}", headers=auth_headers
    )).status_code == 204
    # Estimates are computed on read: retracting the anchor downgrades the state.
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    assert body["status"] == "LOW_CONFIDENCE"
    assert body["estimated_ovulation_date"] is None


@pytest.mark.asyncio
async def test_estimates_retrospective_as_of(async_client: AsyncClient, auth_headers: dict):
    await _make_periods(async_client, auth_headers, _stable_history())
    as_of = _real_today() - timedelta(days=10)
    res = await async_client.get(
        "/api/v1/reproductive/estimates", headers=auth_headers, params={"as_of": str(as_of)}
    )
    assert res.status_code == 200
    assert res.json()["estimate_date"] == str(as_of)
    future = await async_client.get(
        "/api/v1/reproductive/estimates", headers=auth_headers, params={"as_of": str(_real_today() + timedelta(days=3))}
    )
    assert future.status_code == 400


def test_pure_engine_insufficient_low_available_boundaries():
    anchor = date(2026, 1, 28)
    base_kwargs = dict(
        latest_period_start=anchor,
        predicted_cycle_length=28,
        period_confidence="moderate",
        period_source="history",
        variability_mad=0.0,
        timezone_name="Asia/Kolkata",
        now=datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc),
    )
    empty = compute_fertility_estimate(
        as_of=date(2026, 2, 5), cycle_intervals=[], observations=[], **base_kwargs
    )
    assert empty.status == "INSUFFICIENT_DATA"
    assert empty.estimated_ovulation_date is None

    cal_only = compute_fertility_estimate(
        as_of=date(2026, 2, 5), cycle_intervals=[28, 28, 28], observations=[], **base_kwargs
    )
    assert cal_only.status == "LOW_CONFIDENCE"
    assert cal_only.fertile_window_start is None

    unstable = compute_fertility_estimate(
        as_of=date(2026, 2, 5),
        latest_period_start=anchor,
        cycle_intervals=[22, 34, 29],
        predicted_cycle_length=28,
        period_confidence="low",
        period_source="history",
        variability_mad=6.0,
        observations=[ObservationEvidence(date(2026, 2, 1), "lh_test", "positive")],
        timezone_name="Asia/Kolkata",
        now=datetime(2026, 2, 5, 12, 0, tzinfo=timezone.utc),
    )
    assert unstable.status == "LOW_CONFIDENCE"

    ready = compute_fertility_estimate(
        as_of=date(2026, 2, 5),
        cycle_intervals=[28, 28, 28],
        observations=[ObservationEvidence(date(2026, 2, 1), "lh_test", "positive")],
        **base_kwargs,
    )
    assert ready.status == "AVAILABLE"
    assert ready.estimated_ovulation_date == date(2026, 2, 11)
    assert ready.fertile_window_start == date(2026, 2, 6)
    assert ready.fertile_window_end == date(2026, 2, 12)
    assert ready.evidence_source == "OBSERVED"


def test_engine_status_vocabulary_is_closed():
    assert set(ALLOWED_STATUSES) == {"AVAILABLE", "LOW_CONFIDENCE", "INSUFFICIENT_DATA", "SUPPRESSED"}


# --- D. Fertile window safety -------------------------------------------------


@pytest.mark.asyncio
async def test_window_safety_wording(async_client: AsyncClient, auth_headers: dict):
    await _make_periods(async_client, auth_headers, _stable_history())
    await _post_obs(
        async_client, auth_headers,
        {"observation_date": str(_real_today() - timedelta(days=3)), "observation_type": "lh_test", "lh_result": "positive"},
    )
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    text = " ".join(str(v) for v in body.values()).lower()
    assert "safe days" not in text
    assert "unsafe" not in text
    assert "guaranteed" not in text
    assert "not contraception" in body["disclaimer"].lower()
    assert "estimated ovulation" in body["disclaimer"].lower()
    assert "estimated fertile window" in body["disclaimer"].lower()
    start = date.fromisoformat(body["fertile_window_start"])
    end = date.fromisoformat(body["fertile_window_end"])
    ov = date.fromisoformat(body["estimated_ovulation_date"])
    assert (end - start).days == 6
    assert start == ov - timedelta(days=5)
    assert end == ov + timedelta(days=1)


@pytest.mark.asyncio
async def test_lh_positive_not_represented_as_proof(async_client: AsyncClient, auth_headers: dict):
    await _make_periods(async_client, auth_headers, _stable_history())
    await _post_obs(
        async_client, auth_headers,
        {"observation_date": str(_real_today() - timedelta(days=3)), "observation_type": "lh_test", "lh_result": "positive"},
    )
    body = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    text = " ".join(str(v) for v in body.values()).lower()
    # The LH fact is stored verbatim; the estimate never claims proof.
    assert "does not confirm" in body["disclaimer"].lower()
    assert "proof" not in text
    assert "clinically_confirmed" not in text
    listed = await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)
    assert listed.json()[0]["lh_result"] == "positive"


# --- E. Regression ------------------------------------------------------------


@pytest.mark.asyncio
async def test_fertility_data_does_not_alter_period_predictions(
    async_client: AsyncClient, auth_headers: dict
):
    await _make_periods(async_client, auth_headers, _stable_history())
    before = (await async_client.get("/api/v1/summary/current", headers=auth_headers)).json()
    snapshot = {k: before[k] for k in (
        "current_cycle_day", "phase", "is_bleeding", "predicted_next_period",
        "days_until_next_period", "prediction_status", "prediction_confidence",
        "average_cycle_length", "average_period_length",
    )}
    t = _real_today()
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=3)), "observation_type": "lh_test", "lh_result": "positive"})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=2)), "observation_type": "bbt", "bbt_celsius": 36.7})
    await _post_obs(async_client, auth_headers, {"observation_date": str(t - timedelta(days=1)), "observation_type": "cervical_mucus", "mucus_category": "egg_white"})
    after = (await async_client.get("/api/v1/summary/current", headers=auth_headers)).json()
    for key, value in snapshot.items():
        assert after[key] == value, key
    current = (await async_client.get("/api/v1/cycles/current", headers=auth_headers)).json()
    assert current["predicted_next_period"] == snapshot["predicted_next_period"]
    # Period responses carry no fertility dates.
    assert "fertile_window_start" not in current
    assert "estimated_ovulation_date" not in current


@pytest.mark.asyncio
async def test_health_context_still_prediction_independent_with_fertility_present(
    async_client: AsyncClient, auth_headers: dict
):
    await _make_periods(async_client, auth_headers, _stable_history())
    await _post_obs(
        async_client, auth_headers,
        {"observation_date": str(_real_today() - timedelta(days=3)), "observation_type": "lh_test", "lh_result": "positive"},
    )
    before = (await async_client.get("/api/v1/summary/current", headers=auth_headers)).json()
    await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"contraception_method": "fertility_awareness", "pregnancy_context": "avoiding_pregnancy"},
    )
    after = (await async_client.get("/api/v1/summary/current", headers=auth_headers)).json()
    assert after["predicted_next_period"] == before["predicted_next_period"]
    assert after["prediction_confidence"] == before["prediction_confidence"]
    # Legacy pregnancy_context selection does not suppress fertility output.
    est = (await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)).json()
    assert est["status"] == "AVAILABLE"


@pytest.mark.asyncio
async def test_observation_dates_preserved_across_timezones(
    async_client: AsyncClient, auth_headers: dict, frozen_a
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    past = _real_today() + timedelta(days=1) - timedelta(days=4)
    res = await _post_obs(
        async_client, auth_headers,
        {"observation_date": str(past), "observation_type": "bbt", "bbt_celsius": 36.6},
    )
    assert res.status_code == 201, res.text
    assert res.json()["observation_date"] == str(past)
    listed = await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)
    assert listed.json()[0]["observation_date"] == str(past)
    est = await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    assert est.json()["timezone_name"] == KOLKATA


def test_fertility_model_metadata_matches_migration():
    from app.db.base import Base

    tables = Base.metadata.tables
    assert "fertility_observations" in tables
    assert set(tables["fertility_observations"].columns.keys()) == {
        "id", "user_id", "observation_date", "observation_type", "lh_result",
        "bbt_celsius", "mucus_category", "recorded_at", "source", "note",
        "created_at", "updated_at",
    }
    fks = list(tables["fertility_observations"].foreign_keys)
    assert any(
        fk.column.table.name == "profiles" and fk.column.name == "user_id"
        and fk.ondelete == "CASCADE"
        for fk in fks
    )


def test_migration_and_fresh_schema_agree_on_fertility_table():
    from pathlib import Path

    root = Path(__file__).parent.parent
    migration = (root / "migrations" / "0005_fertility_observations_v1.sql").read_text()
    schema = (root / "supabase_initial_schema.sql").read_text()
    for token in (
        "fertility_observations",
        "uq_fertility_obs_user_date_type",
        "ck_fertility_obs_value_matches_type",
        "ck_fertility_obs_bbt_range",
        "ENABLE ROW LEVEL SECURITY",
    ):
        assert token in migration, token
        assert token in schema, token
