"""Phase 3: explicit pregnancy mode + pregnancy dating backend.

Covers: authentication, user isolation, explicit activation (never inferred),
dating sources + provenance + hierarchy protection, EDD / gestational-age
semantics, SUPPRESSED estimates while active, historical-data preservation,
explicit deactivation (never automatic), legacy pregnancy_context
compatibility, cascade + schema agreement, and pure dating-logic units.

Design anchors (see implementation comments for rationale):
- Legacy `health_contexts.pregnancy_context` keeps zero behavioral effect and
  is never reinterpreted; the new `pregnancy_contexts` singleton is the only
  behavioral state. No backfill, no mapping.
- The server never auto-computes an EDD from an LMP date (Phase 1 §8.5);
  EDDs are stored verbatim. Gestational age prefers direct LMP subtraction
  and otherwise uses the named 280-day reference as an estimate.
- Lower-provenance EDDs cannot silently replace higher-provenance EDDs with
  a differing date (409); upgrades and same-date moves are allowed.
- Suppression lives ONLY in the reproductive estimate read path as a
  contextual layer: the frozen period predictor, ledger, backtest, timezone
  implementation, and Health Context behavior are untouched.
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.services.pregnancy_dating import (
    PREGNANCY_GESTATION_DAYS,
    compute_gestational_age_total_days,
    dating_confidence_for,
    edd_label_for,
    is_downgrade_conflict,
    precedence_of,
    split_weeks_days,
)
from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID

KOLKATA = "Asia/Kolkata"


def _today() -> date:
    return date.today()


async def _set_tz(async_client: AsyncClient, headers: dict, tz_name: str) -> None:
    res = await async_client.patch(
        "/api/v1/profile", headers=headers, json={"timezone": tz_name}
    )
    assert res.status_code == 200, res.text


async def _make_periods(async_client: AsyncClient, headers: dict, starts) -> None:
    for s in starts:
        r = await async_client.post(
            "/api/v1/cycles",
            headers=headers,
            json={"period_start": str(s), "period_end": str(s + timedelta(days=4))},
        )
        assert r.status_code == 201, r.text


def _stable_history():
    t = _today()
    return [
        t - timedelta(days=90),
        t - timedelta(days=62),
        t - timedelta(days=34),
        t - timedelta(days=6),
    ]


async def _activate(
    async_client: AsyncClient, headers: dict, payload: dict | None = None
):
    body = {"is_active": True}
    if payload:
        body.update(payload)
    res = await async_client.put("/api/v1/reproductive/pregnancy", headers=headers, json=body)
    assert res.status_code == 200, res.text
    return res.json()


# --- A. Authentication ------------------------------------------------------


@pytest.mark.asyncio
async def test_pregnancy_routes_require_auth(async_client: AsyncClient):
    assert (await async_client.get("/api/v1/reproductive/pregnancy")).status_code == 401
    assert (
        await async_client.put("/api/v1/reproductive/pregnancy", json={})
    ).status_code in (401, 403)
    assert (
        await async_client.patch("/api/v1/reproductive/pregnancy", json={})
    ).status_code in (401, 403)
    assert (
        await async_client.delete("/api/v1/reproductive/pregnancy")
    ).status_code in (401, 403)


@pytest.mark.asyncio
async def test_pregnancy_get_defaults_for_authenticated_user(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["user_id"] == str(TEST_USER_ID)
    assert body["is_active"] is False
    assert body["dating_source"] is None
    assert body["estimated_due_date"] is None
    assert body["edd_status"] == "unavailable"
    assert body["gestational_age_total_days"] is None
    assert body["gestational_age_weeks"] is None
    assert body["gestational_age_days"] is None


# --- B. User isolation ------------------------------------------------------


@pytest.mark.asyncio
async def test_pregnancy_user_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    t = _today()
    await _activate(
        async_client,
        auth_headers,
        {"dating_source": "clinician", "estimated_due_date": str(t + timedelta(days=200))},
    )
    # Another user sees only their own inactive defaults, never the row.
    other = await async_client.get(
        "/api/v1/reproductive/pregnancy", headers=other_user_auth_headers
    )
    assert other.status_code == 200
    assert other.json()["is_active"] is False
    assert other.json()["estimated_due_date"] is None
    # The other user's writes affect only their own singleton.
    await _activate(
        async_client,
        other_user_auth_headers,
        {"dating_source": "lmp", "estimated_due_date": str(t + timedelta(days=150))},
    )
    own = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert own.json()["dating_source"] == "clinician"
    assert own.json()["estimated_due_date"] == str(t + timedelta(days=200))
    # The other user's delete does not touch the owner's row.
    assert (
        await async_client.delete(
            "/api/v1/reproductive/pregnancy", headers=other_user_auth_headers
        )
    ).status_code == 204
    still = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert still.json()["is_active"] is True
    # And the other user's estimates are not suppressed by the owner's mode.
    est = await async_client.get(
        "/api/v1/reproductive/estimates", headers=other_user_auth_headers
    )
    assert est.json()["status"] != "SUPPRESSED"


@pytest.mark.asyncio
async def test_client_supplied_user_id_is_ignored(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    t = _today()
    res = await async_client.put(
        "/api/v1/reproductive/pregnancy",
        headers=auth_headers,
        json={
            "is_active": True,
            "dating_source": "ultrasound",
            "estimated_due_date": str(t + timedelta(days=180)),
            "user_id": str(ANOTHER_USER_ID),
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == str(TEST_USER_ID)
    other = await async_client.get(
        "/api/v1/reproductive/pregnancy", headers=other_user_auth_headers
    )
    assert other.json()["is_active"] is False


@pytest.mark.asyncio
async def test_profile_delete_cascades_pregnancy(
    async_client: AsyncClient, auth_headers: dict
):
    await _activate(async_client, auth_headers)
    assert (await async_client.delete("/api/v1/profile", headers=auth_headers)).status_code == 204
    res = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["is_active"] is False
    assert res.json()["estimated_due_date"] is None


# --- C. Activation (explicit only) ------------------------------------------


@pytest.mark.asyncio
async def test_explicit_activation_without_any_period_history(
    async_client: AsyncClient, other_user_auth_headers: dict
):
    # A fresh user with zero periods can activate: mode never depends on a
    # late or missing period.
    body = await _activate(async_client, other_user_auth_headers)
    assert body["is_active"] is True
    assert body["edd_status"] == "unavailable"


@pytest.mark.asyncio
async def test_activation_with_unknown_dating_is_valid(
    async_client: AsyncClient, auth_headers: dict
):
    body = await _activate(async_client, auth_headers, {"dating_source": "unknown"})
    assert body["is_active"] is True
    assert body["dating_source"] == "unknown"
    assert body["estimated_due_date"] is None
    assert body["edd_status"] == "unavailable"
    assert body["dating_confidence"] == "UNKNOWN"
    assert body["gestational_age_total_days"] is None


@pytest.mark.asyncio
async def test_legacy_pregnancy_context_does_not_activate_mode(
    async_client: AsyncClient, auth_headers: dict
):
    await _make_periods(async_client, auth_headers, _stable_history())
    t = _today()
    lh = await async_client.post(
        "/api/v1/reproductive/observations",
        headers=auth_headers,
        json={
            "observation_date": str(t - timedelta(days=3)),
            "observation_type": "lh_test",
            "lh_result": "positive",
        },
    )
    assert lh.status_code == 201
    assert (
        await async_client.put(
            "/api/v1/health-context",
            headers=auth_headers,
            json={"pregnancy_context": "pregnant"},
        )
    ).status_code == 200
    # Legacy selection has zero behavioral effect: mode stays off, estimates stay AVAILABLE.
    mode = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert mode.json()["is_active"] is False
    est = await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    assert est.json()["status"] == "AVAILABLE"


@pytest.mark.asyncio
async def test_pregnancy_activation_leaves_legacy_field_untouched(
    async_client: AsyncClient, auth_headers: dict
):
    before = await async_client.get("/api/v1/health-context", headers=auth_headers)
    assert before.json()["pregnancy_context"] is None
    await _activate(async_client, auth_headers)
    after = await async_client.get("/api/v1/health-context", headers=auth_headers)
    assert after.json()["pregnancy_context"] is None


# --- D. Dating --------------------------------------------------------------


@pytest.mark.asyncio
async def test_lmp_dating_and_provenance(async_client: AsyncClient, auth_headers: dict):
    t = _today()
    lmp = t - timedelta(days=80)
    edd = t + timedelta(days=200)  # consistent 280-day span, stored verbatim
    body = await _activate(
        async_client,
        auth_headers,
        {
            "dating_source": "lmp",
            "lmp_date": str(lmp),
            "estimated_due_date": str(edd),
            "confirmation_date": str(t - timedelta(days=50)),
            "dating_note": "LMP recalled from calendar",
        },
    )
    assert body["dating_source"] == "lmp"
    assert body["estimated_due_date"] == str(edd)
    assert body["lmp_date"] == str(lmp)
    assert body["edd_status"] == "available"
    assert body["edd_label"] == "estimated_due_date"
    assert body["dating_confidence"] == "ESTIMATED"
    assert body["dating_note"] == "LMP recalled from calendar"


@pytest.mark.asyncio
async def test_clinician_dating_is_confirmed_not_estimated(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    body = await _activate(
        async_client,
        auth_headers,
        {"dating_source": "clinician", "estimated_due_date": str(t + timedelta(days=200))},
    )
    assert body["edd_label"] == "clinician_established_due_date"
    assert body["dating_confidence"] == "CLINICALLY_CONFIRMED"


@pytest.mark.asyncio
async def test_ultrasound_dating_is_estimated(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    body = await _activate(
        async_client,
        auth_headers,
        {"dating_source": "ultrasound", "estimated_due_date": str(t + timedelta(days=190))},
    )
    assert body["edd_label"] == "estimated_due_date"
    assert body["dating_confidence"] == "ESTIMATED"


@pytest.mark.asyncio
async def test_server_does_not_invent_edd_from_lmp(
    async_client: AsyncClient, auth_headers: dict
):
    # LMP alone (no EDD supplied) yields unavailable EDD: the server never
    # auto-computes LMP + 280d. Gestational age still derives directly from LMP.
    t = _today()
    lmp = t - timedelta(days=80)
    body = await _activate(
        async_client, auth_headers, {"dating_source": "lmp", "lmp_date": str(lmp)}
    )
    assert body["estimated_due_date"] is None
    assert body["edd_status"] == "unavailable"
    as_of = date.fromisoformat(body["as_of_date"])
    assert body["gestational_age_total_days"] == (as_of - lmp).days


@pytest.mark.asyncio
async def test_higher_provenance_protected_from_silent_overwrite(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    await _activate(
        async_client,
        auth_headers,
        {"dating_source": "clinician", "estimated_due_date": str(t + timedelta(days=200))},
    )
    # Lower-provenance differing EDDs are rejected, never silently applied.
    for source, edd in (
        ("lmp", t + timedelta(days=195)),
        ("ultrasound", t + timedelta(days=197)),
    ):
        payload = {"dating_source": source, "estimated_due_date": str(edd)}
        if source == "lmp":
            payload["lmp_date"] = str(t - timedelta(days=80))
        res = await async_client.put(
            "/api/v1/reproductive/pregnancy", headers=auth_headers, json=payload
        )
        assert res.status_code == 409, (source, res.text)
        res = await async_client.patch(
            "/api/v1/reproductive/pregnancy", headers=auth_headers, json=payload
        )
        assert res.status_code == 409, (source, res.text)
    # Stored clinician date is intact.
    kept = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert kept.json()["dating_source"] == "clinician"
    assert kept.json()["estimated_due_date"] == str(t + timedelta(days=200))


@pytest.mark.asyncio
async def test_ultrasound_protected_from_lmp_overwrite(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    await _activate(
        async_client,
        auth_headers,
        {"dating_source": "ultrasound", "estimated_due_date": str(t + timedelta(days=190))},
    )
    res = await async_client.patch(
        "/api/v1/reproductive/pregnancy",
        headers=auth_headers,
        json={
            "dating_source": "lmp",
            "lmp_date": str(t - timedelta(days=80)),
            "estimated_due_date": str(t + timedelta(days=195)),
        },
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_upgrade_and_same_date_moves_allowed(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    edd = t + timedelta(days=200)
    await _activate(
        async_client,
        auth_headers,
        {
            "dating_source": "lmp",
            "lmp_date": str(t - timedelta(days=80)),
            "estimated_due_date": str(edd),
        },
    )
    # Upgrade lmp -> clinician with a (refined) differing date is allowed
    # (lmp_date is cleared as part of the move: it is provenance for lmp only).
    up = await async_client.patch(
        "/api/v1/reproductive/pregnancy",
        headers=auth_headers,
        json={
            "dating_source": "clinician",
            "estimated_due_date": str(t + timedelta(days=198)),
            "lmp_date": None,
        },
    )
    assert up.status_code == 200, up.text
    assert up.json()["dating_confidence"] == "CLINICALLY_CONFIRMED"
    # Same-date provenance move back down is not a date conflict: allowed.
    down = await async_client.patch(
        "/api/v1/reproductive/pregnancy",
        headers=auth_headers,
        json={"dating_source": "lmp", "estimated_due_date": str(t + timedelta(days=198))},
    )
    assert down.status_code == 200, down.text


@pytest.mark.asyncio
async def test_invalid_and_conflicting_input_rejected(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    # EDD without a known source.
    assert (
        await async_client.put(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={"is_active": True, "estimated_due_date": str(t + timedelta(days=200))},
        )
    ).status_code == 400
    # EDD claimed as unknown.
    assert (
        await async_client.put(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={
                "is_active": True,
                "dating_source": "unknown",
                "estimated_due_date": str(t + timedelta(days=200)),
            },
        )
    ).status_code == 400
    # lmp_date under a non-lmp source.
    assert (
        await async_client.put(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={
                "is_active": True,
                "dating_source": "clinician",
                "estimated_due_date": str(t + timedelta(days=200)),
                "lmp_date": str(t - timedelta(days=80)),
            },
        )
    ).status_code == 400
    # Future LMP / future confirmation (schema coarse guard answers 422 for
    # far-future dates, the user-local route bound answers 400: both reject).
    assert (
        await async_client.put(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={
                "is_active": True,
                "dating_source": "lmp",
                "lmp_date": str(t + timedelta(days=2)),
            },
        )
    ).status_code in (400, 422)
    assert (
        await async_client.put(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={"is_active": True, "confirmation_date": str(t + timedelta(days=2))},
        )
    ).status_code in (400, 422)
    # Chronology violations (both dates past, but lmp after edd).
    assert (
        await async_client.put(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={
                "is_active": True,
                "dating_source": "lmp",
                "lmp_date": str(t - timedelta(days=10)),
                "estimated_due_date": str(t - timedelta(days=20)),
            },
        )
    ).status_code == 400
    # Unknown enum + over-long note.
    assert (
        await async_client.put(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={"is_active": True, "dating_source": "blood_test"},
        )
    ).status_code == 422
    assert (
        await async_client.patch(
            "/api/v1/reproductive/pregnancy",
            headers=auth_headers,
            json={"dating_note": "x" * 1001},
        )
    ).status_code == 422


# --- E. EDD / gestational age -----------------------------------------------


@pytest.mark.asyncio
async def test_edd_and_gestational_age_from_lmp_and_edd(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    lmp = t - timedelta(days=80)
    edd = t + timedelta(days=200)
    body = await _activate(
        async_client,
        auth_headers,
        {"dating_source": "lmp", "lmp_date": str(lmp), "estimated_due_date": str(edd)},
    )
    as_of = date.fromisoformat(body["as_of_date"])
    # Direct LMP subtraction governs when LMP is known.
    assert body["gestational_age_total_days"] == (as_of - lmp).days == 80
    assert body["gestational_age_weeks"] == 11
    assert body["gestational_age_days"] == 3
    assert body["days_until_due"] == (edd - as_of).days == 200


@pytest.mark.asyncio
async def test_gestational_age_from_edd_only_uses_280_day_reference(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    edd = t + timedelta(days=200)
    body = await _activate(
        async_client,
        auth_headers,
        {"dating_source": "ultrasound", "estimated_due_date": str(edd)},
    )
    as_of = date.fromisoformat(body["as_of_date"])
    assert body["gestational_age_total_days"] == 280 - (edd - as_of).days == 80
    assert (body["gestational_age_weeks"], body["gestational_age_days"]) == (11, 3)


@pytest.mark.asyncio
async def test_unavailable_state_when_no_dating(
    async_client: AsyncClient, auth_headers: dict
):
    body = await _activate(async_client, auth_headers)
    assert body["estimated_due_date"] is None
    assert body["edd_status"] == "unavailable"
    assert body["dating_confidence"] == "UNKNOWN"
    assert body["gestational_age_total_days"] is None
    assert body["gestational_age_weeks"] is None
    assert body["gestational_age_days"] is None
    assert body["days_until_due"] is None


@pytest.mark.asyncio
async def test_post_term_pregnancy_stays_active_with_negative_countdown(
    async_client: AsyncClient, auth_headers: dict
):
    # A passed EDD never auto-exits the mode; the countdown goes negative and
    # gestational age keeps counting (41w3d here).
    t = _today()
    body = await _activate(
        async_client,
        auth_headers,
        {"dating_source": "clinician", "estimated_due_date": str(t - timedelta(days=10))},
    )
    assert body["is_active"] is True
    assert body["edd_status"] == "available"
    as_of = date.fromisoformat(body["as_of_date"])
    assert body["days_until_due"] == -10 or body["days_until_due"] == ((t - timedelta(days=10)) - as_of).days
    assert body["gestational_age_total_days"] == 290
    assert (body["gestational_age_weeks"], body["gestational_age_days"]) == (41, 3)
    est = await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    assert est.json()["status"] == "SUPPRESSED"


@pytest.mark.asyncio
async def test_pregnancy_dates_use_local_calendar_semantics(
    async_client: AsyncClient, auth_headers: dict
):
    await _set_tz(async_client, auth_headers, KOLKATA)
    t = _today()
    edd = t + timedelta(days=200)
    body = await _activate(
        async_client,
        auth_headers,
        {"dating_source": "clinician", "estimated_due_date": str(edd)},
    )
    # DATEs are preserved exactly (never shifted through UTC).
    assert body["estimated_due_date"] == str(edd)
    assert body["timezone_name"] == KOLKATA
    assert date.fromisoformat(body["as_of_date"]) is not None


# --- F. Suppression ----------------------------------------------------------


@pytest.mark.asyncio
async def test_estimates_suppressed_while_active(
    async_client: AsyncClient, auth_headers: dict
):
    starts = _stable_history()
    await _make_periods(async_client, auth_headers, starts)
    t = _today()
    lh = await async_client.post(
        "/api/v1/reproductive/observations",
        headers=auth_headers,
        json={
            "observation_date": str(t - timedelta(days=3)),
            "observation_type": "lh_test",
            "lh_result": "positive",
        },
    )
    assert lh.status_code == 201
    assert (
        await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    ).json()["status"] == "AVAILABLE"
    await _activate(async_client, auth_headers)
    body = (
        await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    ).json()
    assert body["status"] == "SUPPRESSED"
    assert body["estimated_ovulation_date"] is None
    assert body["fertile_window_start"] is None
    assert body["fertile_window_end"] is None
    # No current next-period prediction leaks through the pregnancy-aware contract.
    assert "predicted_next_period" not in body
    assert "estimated_next_period" not in body
    assert "next_period" not in body
    assert body["evidence"].get("pregnancy_mode_active") is True


@pytest.mark.asyncio
async def test_inactive_mode_preserves_phase2_behavior(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    assert res.json()["status"] == "INSUFFICIENT_DATA"


@pytest.mark.asyncio
async def test_period_predictor_untouched_by_pregnancy_mode(
    async_client: AsyncClient, auth_headers: dict
):
    # The frozen predictor keeps serving historical math; suppression applies
    # only to the reproductive estimate contract (contextual layer, no
    # predictor modification).
    await _make_periods(async_client, auth_headers, _stable_history())
    before = (
        await async_client.get("/api/v1/summary/current", headers=auth_headers)
    ).json()
    await _activate(async_client, auth_headers)
    after = (
        await async_client.get("/api/v1/summary/current", headers=auth_headers)
    ).json()
    assert after["predicted_next_period"] == before["predicted_next_period"]
    current = (
        await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    ).json()
    assert current["predicted_next_period"] == before["predicted_next_period"]


# --- G. Historical data ------------------------------------------------------


@pytest.mark.asyncio
async def test_activation_preserves_all_historical_data(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    await _make_periods(async_client, auth_headers, _stable_history())
    obs = await async_client.post(
        "/api/v1/reproductive/observations",
        headers=auth_headers,
        json={
            "observation_date": str(t - timedelta(days=2)),
            "observation_type": "bbt",
            "bbt_celsius": 36.6,
        },
    )
    assert obs.status_code == 201
    log_day = t - timedelta(days=2)
    log = await async_client.post(
        "/api/v1/logs", headers=auth_headers, json={"log_date": str(log_day), "pain": 3}
    )
    assert log.status_code == 200
    await _activate(
        async_client,
        auth_headers,
        {"dating_source": "clinician", "estimated_due_date": str(t + timedelta(days=200))},
    )
    assert len((await async_client.get("/api/v1/cycles", headers=auth_headers)).json()) == 4
    assert (
        len((await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)).json())
        == 1
    )
    reread = await async_client.get(f"/api/v1/logs/{log_day}", headers=auth_headers)
    assert reread.status_code == 200
    assert reread.json()["pain"] == 3


# --- H. Deactivation (explicit only) -----------------------------------------


@pytest.mark.asyncio
async def test_explicit_deactivation_restores_estimates(
    async_client: AsyncClient, auth_headers: dict
):
    await _activate(async_client, auth_headers)
    assert (
        await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    ).json()["status"] == "SUPPRESSED"
    res = await async_client.patch(
        "/api/v1/reproductive/pregnancy", headers=auth_headers, json={"is_active": False}
    )
    assert res.status_code == 200
    assert res.json()["is_active"] is False
    # History retained (row still present), suppression lifted.
    assert (
        await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    ).json()["status"] == "INSUFFICIENT_DATA"


@pytest.mark.asyncio
async def test_logging_a_period_does_not_deactivate(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    await _activate(async_client, auth_headers)
    # Logging new cycle data while active is stored normally but never flips mode.
    r = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={
            "period_start": str(t - timedelta(days=5)),
            "period_end": str(t - timedelta(days=1)),
        },
    )
    assert r.status_code == 201, r.text
    mode = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert mode.json()["is_active"] is True
    assert (
        await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    ).json()["status"] == "SUPPRESSED"


@pytest.mark.asyncio
async def test_put_patch_delete_lifecycle(async_client: AsyncClient, auth_headers: dict):
    t = _today()
    full = await _activate(
        async_client,
        auth_headers,
        {
            "dating_source": "ultrasound",
            "estimated_due_date": str(t + timedelta(days=190)),
            "dating_note": "scan",
        },
    )
    assert full["dating_note"] == "scan"
    # PUT full replacement clears omitted dating fields.
    replaced = await async_client.put(
        "/api/v1/reproductive/pregnancy", headers=auth_headers, json={"is_active": True}
    )
    assert replaced.status_code == 200
    assert replaced.json()["dating_source"] is None
    assert replaced.json()["estimated_due_date"] is None
    assert replaced.json()["edd_status"] == "unavailable"
    # PATCH partial preserves unmentioned fields.
    await _activate(
        async_client,
        auth_headers,
        {"dating_source": "lmp", "estimated_due_date": str(t + timedelta(days=200))},
    )
    patched = await async_client.patch(
        "/api/v1/reproductive/pregnancy", headers=auth_headers, json={"dating_note": "n"}
    )
    assert patched.json()["dating_note"] == "n"
    assert patched.json()["estimated_due_date"] == str(t + timedelta(days=200))
    # Explicit null clears the note only.
    cleared = await async_client.patch(
        "/api/v1/reproductive/pregnancy", headers=auth_headers, json={"dating_note": None}
    )
    assert cleared.json()["dating_note"] is None
    assert cleared.json()["estimated_due_date"] == str(t + timedelta(days=200))
    # DELETE erases; estimates recover.
    assert (
        await async_client.delete("/api/v1/reproductive/pregnancy", headers=auth_headers)
    ).status_code == 204
    gone = await async_client.get("/api/v1/reproductive/pregnancy", headers=auth_headers)
    assert gone.json()["is_active"] is False
    assert (
        await async_client.get("/api/v1/reproductive/estimates", headers=auth_headers)
    ).json()["status"] == "INSUFFICIENT_DATA"


# --- Pure dating-logic units --------------------------------------------------


def test_gestation_reference_is_280_days():
    assert PREGNANCY_GESTATION_DAYS == 280


def test_compute_gestational_age_vectors():
    as_of = date(2026, 5, 20)
    # LMP direct subtraction governs.
    assert (
        compute_gestational_age_total_days(
            estimated_due_date=date(2026, 12, 6),
            lmp_date=date(2026, 2, 28),
            as_of=as_of,
        )
        == (as_of - date(2026, 2, 28)).days
    )
    # EDD-only fallback via the 280-day reference.
    assert (
        compute_gestational_age_total_days(
            estimated_due_date=date(2026, 12, 6), lmp_date=None, as_of=as_of
        )
        == 280 - (date(2026, 12, 6) - as_of).days
    )
    # Unavailable when no basis.
    assert (
        compute_gestational_age_total_days(
            estimated_due_date=None, lmp_date=None, as_of=as_of
        )
        is None
    )
    # Inconsistent far-future EDD clamps instead of going negative.
    assert (
        compute_gestational_age_total_days(
            estimated_due_date=date(2027, 6, 1), lmp_date=None, as_of=as_of
        )
        == 0
    )
    assert split_weeks_days(80) == (11, 3)
    assert split_weeks_days(None) == (None, None)


def test_precedence_confidence_and_labels():
    assert precedence_of("clinician") > precedence_of("ultrasound") > precedence_of("lmp")
    assert precedence_of("lmp") > precedence_of("unknown") > precedence_of(None)
    assert dating_confidence_for("clinician") == "CLINICALLY_CONFIRMED"
    assert dating_confidence_for("ultrasound") == "ESTIMATED"
    assert dating_confidence_for("lmp") == "ESTIMATED"
    assert dating_confidence_for("unknown") == "UNKNOWN"
    assert dating_confidence_for(None) == "UNKNOWN"
    assert edd_label_for("clinician") == "clinician_established_due_date"
    assert edd_label_for("lmp") == "estimated_due_date"
    assert edd_label_for(None) == "estimated_due_date"


def test_downgrade_conflict_matrix():
    edd_a = date(2026, 12, 1)
    edd_b = date(2026, 12, 5)
    # Lower over higher with differing EDD: conflict.
    assert is_downgrade_conflict(
        existing_source="clinician", existing_edd=edd_a,
        incoming_source="lmp", incoming_edd=edd_b,
    )
    assert is_downgrade_conflict(
        existing_source="clinician", existing_edd=edd_a,
        incoming_source="ultrasound", incoming_edd=edd_b,
    )
    assert is_downgrade_conflict(
        existing_source="ultrasound", existing_edd=edd_a,
        incoming_source="lmp", incoming_edd=edd_b,
    )
    # Same date: never a conflict (provenance move, no medical disagreement).
    assert not is_downgrade_conflict(
        existing_source="clinician", existing_edd=edd_a,
        incoming_source="lmp", incoming_edd=edd_a,
    )
    # Upgrades and lateral moves: allowed.
    assert not is_downgrade_conflict(
        existing_source="lmp", existing_edd=edd_a,
        incoming_source="clinician", incoming_edd=edd_b,
    )
    assert not is_downgrade_conflict(
        existing_source="lmp", existing_edd=edd_a,
        incoming_source="lmp", incoming_edd=edd_b,
    )
    # Missing EDD on either side: no date conflict.
    assert not is_downgrade_conflict(
        existing_source="clinician", existing_edd=None,
        incoming_source="lmp", incoming_edd=edd_b,
    )
    assert not is_downgrade_conflict(
        existing_source="clinician", existing_edd=edd_a,
        incoming_source="lmp", incoming_edd=None,
    )


# --- Schema / migration agreement ---------------------------------------------


def test_pregnancy_model_metadata_matches_migration():
    from app.db.base import Base

    tables = Base.metadata.tables
    assert "pregnancy_contexts" in tables
    assert set(tables["pregnancy_contexts"].columns.keys()) == {
        "user_id", "is_active", "dating_source", "estimated_due_date", "lmp_date",
        "confirmation_date", "dating_note", "created_at", "updated_at",
    }
    fks = list(tables["pregnancy_contexts"].foreign_keys)
    assert any(
        fk.column.table.name == "profiles" and fk.column.name == "user_id"
        and fk.ondelete == "CASCADE"
        for fk in fks
    )


def test_migration_and_fresh_schema_agree_on_pregnancy_table():
    from pathlib import Path

    root = Path(__file__).parent.parent
    migration = (root / "migrations" / "0006_pregnancy_context_v1.sql").read_text()
    schema = (root / "supabase_initial_schema.sql").read_text()
    for token in (
        "pregnancy_contexts",
        "ck_pregnancy_dating_source",
        "ck_pregnancy_edd_requires_known_source",
        "ck_pregnancy_lmp_only_for_lmp_source",
        "ck_pregnancy_lmp_before_edd",
        "ck_pregnancy_confirmation_before_edd",
        "ENABLE ROW LEVEL SECURITY",
    ):
        assert token in migration, token
        assert token in schema, token
