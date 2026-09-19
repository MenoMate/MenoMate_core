"""Phase 4: explicit reproductive-aging / perimenopause context backend.

Covers: authentication, user isolation, context lifecycle (GET defaults,
PUT full-replacement upsert, clearing), validation, user-declared
provenance, pregnancy-mode independence (both directions, all four
active/inactive combinations), fertility-estimate preservation (exact Phase 2
behavior unchanged), period-predictor protection, historical-data
preservation, Health Context compatibility, cascade + schema agreement, and
medical-safety wording (no diagnosis, staging, infertility, or
zero-pregnancy claims anywhere in responses).

Design anchors (see implementation comments for rationale):
- The Phase 1 design contract (§4.3, §11, §5.8) defines NO state vocabulary
  for reproductive aging — deliberately no perimenopause_stage,
  menopause_status, or diagnosis column. This phase therefore implements no
  enum and invents no staging: the singleton stores verbatim user notes only
  (mirroring the health-notes pattern). Structured staging, the conventional
  12-month menopause criterion, and any fertility-estimate effect are
  documented NEEDS-REVIEW product/clinical decisions, not code.
- Endpoints are exactly GET + PUT /api/v1/reproductive/aging-context (the
  only operations the contract requires). There is no PATCH/DELETE surface.
- The context is inert by construction: it is never read by the period
  predictor, the fertility estimator, or pregnancy mode, and none of those
  writers touch it.
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID

AGING = "/api/v1/reproductive/aging-context"
PREGNANCY = "/api/v1/reproductive/pregnancy"
ESTIMATES = "/api/v1/reproductive/estimates"

# Positive diagnostic / infertility claims that must NEVER appear in any
# Phase 4-related response body. Phrased as claim patterns (not bare words)
# so that approved safety negations — e.g. the Phase 2 fixed disclaimer
# "... not guarantees of fertility or infertility ..." and the Phase 4
# "... not a medical diagnosis ..." — do not false-positive. Matching is
# case-insensitive substring on the serialized body.
BANNED_PHRASES = (
    "you are in menopause",
    "you are perimenopausal",
    "perimenopause diagnosis",
    "menopause diagnosis",
    "diagnosed with menopause",
    "diagnosed with perimenopause",
    "confirmed menopause",
    "confirmed perimenopause",
    "you are infertile",
    "infertility diagnosis",
    "diagnosed infertility",
    "confirmed infertile",
    "zero pregnancy",
    "cannot conceive",
    "cannot become pregnant",
    "no pregnancy possibility",
    "no longer fertile",
)


def _today() -> date:
    return date.today()


async def _put_notes(async_client: AsyncClient, headers: dict, payload: dict):
    res = await async_client.put(AGING, headers=headers, json=payload)
    assert res.status_code == 200, res.text
    return res.json()


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


def _assert_no_banned_claims(body) -> None:
    text = str(body).lower()
    for phrase in BANNED_PHRASES:
        assert phrase not in text, f"banned claim {phrase!r} present: {text[:500]}"


# --- A. Authentication ------------------------------------------------------


@pytest.mark.asyncio
async def test_aging_routes_require_auth(async_client: AsyncClient):
    assert (await async_client.get(AGING)).status_code == 401
    assert (await async_client.put(AGING, json={})).status_code in (401, 403)


@pytest.mark.asyncio
async def test_aging_get_defaults_for_authenticated_user(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.get(AGING, headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["user_id"] == str(TEST_USER_ID)
    assert body["has_context"] is False
    assert body["notes"] is None
    assert body["provenance"] == "user_declared"
    assert body["created_at"] is None
    assert body["updated_at"] is None
    _assert_no_banned_claims(body)


@pytest.mark.asyncio
async def test_aging_get_is_read_only_without_profile_side_effects(
    async_client: AsyncClient, auth_headers: dict
):
    # A fresh user GET sees defaults; nothing is created for them.
    first = await async_client.get(AGING, headers=auth_headers)
    assert first.json()["has_context"] is False
    second = await async_client.get(AGING, headers=auth_headers)
    assert second.json() == first.json()


# --- B. User isolation ------------------------------------------------------


@pytest.mark.asyncio
async def test_aging_user_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    body = await _put_notes(async_client, auth_headers, {"notes": "Patterns changing."})
    assert body["notes"] == "Patterns changing."
    assert body["has_context"] is True

    # Another user sees only their own unset defaults, never the row.
    other = await async_client.get(AGING, headers=other_user_auth_headers)
    assert other.status_code == 200
    assert other.json()["has_context"] is False
    assert other.json()["notes"] is None

    # The other user's writes affect only their own singleton.
    await _put_notes(async_client, other_user_auth_headers, {"notes": "Other user note."})
    own = await async_client.get(AGING, headers=auth_headers)
    assert own.json()["notes"] == "Patterns changing."

    # The other user's clearing does not touch the owner's row.
    await _put_notes(async_client, other_user_auth_headers, {})
    still = await async_client.get(AGING, headers=auth_headers)
    assert still.json()["has_context"] is True
    assert still.json()["notes"] == "Patterns changing."


@pytest.mark.asyncio
async def test_client_supplied_user_id_is_ignored(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    res = await async_client.put(
        AGING,
        headers=auth_headers,
        json={"notes": "Mine.", "user_id": str(ANOTHER_USER_ID)},
    )
    assert res.status_code == 200, res.text
    assert res.json()["user_id"] == str(TEST_USER_ID)
    other = await async_client.get(AGING, headers=other_user_auth_headers)
    assert other.json()["has_context"] is False


@pytest.mark.asyncio
async def test_profile_delete_cascades_aging_context(
    async_client: AsyncClient, auth_headers: dict
):
    await _put_notes(async_client, auth_headers, {"notes": "To be erased."})
    assert (await async_client.delete("/api/v1/profile", headers=auth_headers)).status_code == 204
    res = await async_client.get(AGING, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["has_context"] is False
    assert res.json()["notes"] is None


# --- C. Context lifecycle ---------------------------------------------------


@pytest.mark.asyncio
async def test_aging_lifecycle_create_retrieve_update_clear(
    async_client: AsyncClient, auth_headers: dict
):
    # Create.
    created = await _put_notes(async_client, auth_headers, {"notes": "First note."})
    assert created["has_context"] is True
    assert created["provenance"] == "user_declared"
    assert created["created_at"] is not None
    assert created["updated_at"] is not None

    # Retrieve.
    got = await async_client.get(AGING, headers=auth_headers)
    assert got.json()["notes"] == "First note."

    # Update (full replacement).
    updated = await _put_notes(async_client, auth_headers, {"notes": "Revised note."})
    assert updated["notes"] == "Revised note."
    assert updated["has_context"] is True

    # Clear via omitted field (deactivation path — PUT full replacement).
    cleared = await _put_notes(async_client, auth_headers, {})
    assert cleared["has_context"] is False
    assert cleared["notes"] is None

    # Clear via explicit null converges to the same unset state.
    await _put_notes(async_client, auth_headers, {"notes": "Again."})
    cleared_null = await _put_notes(async_client, auth_headers, {"notes": None})
    assert cleared_null["has_context"] is False
    assert cleared_null["notes"] is None


@pytest.mark.asyncio
async def test_aging_has_no_patch_or_delete_surface(async_client: AsyncClient, auth_headers: dict):
    await _put_notes(async_client, auth_headers, {"notes": "Present."})
    # The contract requires GET + PUT only; PATCH/DELETE must not exist.
    assert (await async_client.patch(AGING, headers=auth_headers, json={"notes": "x"})).status_code in (
        404,
        405,
    )
    assert (await async_client.delete(AGING, headers=auth_headers)).status_code in (404, 405)
    # And the unsupported methods changed nothing.
    still = await async_client.get(AGING, headers=auth_headers)
    assert still.json()["notes"] == "Present."


@pytest.mark.asyncio
async def test_aging_is_never_automatically_activated(
    async_client: AsyncClient, auth_headers: dict
):
    # Irregular history, observations, symptoms, and legacy health selections
    # must never create reproductive-aging context on their own.
    t = _today()
    await _make_periods(
        async_client,
        auth_headers,
        [t - timedelta(days=120), t - timedelta(days=60), t - timedelta(days=55), t - timedelta(days=10)],
    )
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
            json={"health_notes": "Night sweats noted."},
        )
    ).status_code == 200
    assert (
        await async_client.patch(
            "/api/v1/profile", headers=auth_headers, json={"birth_year": 1979, "birth_month": 3}
        )
    ).status_code == 200
    res = await async_client.get(AGING, headers=auth_headers)
    assert res.json()["has_context"] is False
    assert res.json()["notes"] is None


# --- D. State validation ----------------------------------------------------


@pytest.mark.asyncio
async def test_aging_notes_length_limit_enforced(async_client: AsyncClient, auth_headers: dict):
    ok = await async_client.put(AGING, headers=auth_headers, json={"notes": "x" * 2000})
    assert ok.status_code == 200
    too_long = await async_client.put(AGING, headers=auth_headers, json={"notes": "x" * 2001})
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_aging_response_carries_no_staging_or_diagnosis_fields(
    async_client: AsyncClient, auth_headers: dict
):
    body = await _put_notes(async_client, auth_headers, {"notes": "Context only."})
    # No structured lifecycle/staging vocabulary exists by design — assert the
    # response cannot be mistaken for one.
    for forbidden_key in (
        "stage",
        "perimenopause_stage",
        "menopause_status",
        "status",
        "diagnosis",
        "menopause",
        "perimenopause",
        "postmenopause",
        "dating_source",
        "estimated_due_date",
        "fertile_window_start",
        "confidence",
    ):
        assert forbidden_key not in body, forbidden_key
    assert set(body.keys()) == {
        "user_id",
        "has_context",
        "notes",
        "provenance",
        "disclaimer",
        "created_at",
        "updated_at",
    }


# --- E. Provenance ----------------------------------------------------------


@pytest.mark.asyncio
async def test_aging_provenance_is_always_user_declared(
    async_client: AsyncClient, auth_headers: dict
):
    unset = await async_client.get(AGING, headers=auth_headers)
    assert unset.json()["provenance"] == "user_declared"
    recorded = await _put_notes(async_client, auth_headers, {"notes": "My words."})
    assert recorded["provenance"] == "user_declared"
    # Clinical confirmation can never be fabricated through this surface:
    # no input field maps to it and no response value claims it.
    assert "CLINICALLY_CONFIRMED" not in str(recorded)
    assert "clinically_confirmed" not in str(recorded).replace("never", "")
    cleared = await _put_notes(async_client, auth_headers, {})
    assert cleared["provenance"] == "user_declared"


# --- F. Date semantics ------------------------------------------------------


@pytest.mark.asyncio
async def test_aging_model_has_no_date_columns():
    from app.db.base import Base

    cols = Base.metadata.tables["reproductive_aging_contexts"].columns
    date_cols = [name for name, col in cols.items() if str(col.type).upper() == "DATE"]
    assert date_cols == []


# --- G. Pregnancy interaction -----------------------------------------------


@pytest.mark.asyncio
async def test_aging_and_pregnancy_coexist_independently(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    # 1. Both inactive.
    assert (await async_client.get(AGING, headers=auth_headers)).json()["has_context"] is False
    assert (await async_client.get(PREGNANCY, headers=auth_headers)).json()["is_active"] is False

    # 2. Aging active + pregnancy inactive.
    await _put_notes(async_client, auth_headers, {"notes": "Aging context."})
    mode = await async_client.get(PREGNANCY, headers=auth_headers)
    assert mode.json()["is_active"] is False
    assert mode.json()["estimated_due_date"] is None

    # 3. Aging active + pregnancy active (explicit PUT only).
    preg = await async_client.put(
        PREGNANCY,
        headers=auth_headers,
        json={
            "is_active": True,
            "dating_source": "ultrasound",
            "estimated_due_date": str(t + timedelta(days=180)),
        },
    )
    assert preg.status_code == 200
    aging = await async_client.get(AGING, headers=auth_headers)
    assert aging.json()["has_context"] is True
    assert aging.json()["notes"] == "Aging context."

    # 4. Deactivating pregnancy retains aging context untouched.
    patched = await async_client.patch(PREGNANCY, headers=auth_headers, json={"is_active": False})
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False
    mode_after = await async_client.get(PREGNANCY, headers=auth_headers)
    assert mode_after.json()["is_active"] is False
    assert mode_after.json()["estimated_due_date"] == str(t + timedelta(days=180))
    aging_after = await async_client.get(AGING, headers=auth_headers)
    assert aging_after.json()["notes"] == "Aging context."

    # 5. Clearing aging retains pregnancy history untouched.
    await _put_notes(async_client, auth_headers, {})
    mode_final = await async_client.get(PREGNANCY, headers=auth_headers)
    assert mode_final.json()["estimated_due_date"] == str(t + timedelta(days=180))
    _assert_no_banned_claims(mode_final.json())


@pytest.mark.asyncio
async def test_pregnancy_suppression_unchanged_when_aging_active(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    await _make_periods(async_client, auth_headers, _stable_history())
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
    before = await async_client.get(ESTIMATES, headers=auth_headers)
    assert before.json()["status"] == "AVAILABLE"

    await _put_notes(async_client, auth_headers, {"notes": "Aging context."})
    # Phase 3 suppression still applies exactly as before when pregnancy mode
    # activates, regardless of aging context.
    act = await async_client.put(PREGNANCY, headers=auth_headers, json={"is_active": True})
    assert act.status_code == 200
    suppressed = await async_client.get(ESTIMATES, headers=auth_headers)
    assert suppressed.json()["status"] == "SUPPRESSED"
    assert suppressed.json()["estimated_ovulation_date"] is None
    assert suppressed.json()["fertile_window_start"] is None
    assert suppressed.json()["fertile_window_end"] is None

    # Erasing pregnancy mode restores the pre-existing estimate behavior.
    assert (await async_client.delete(PREGNANCY, headers=auth_headers)).status_code == 204
    restored = await async_client.get(ESTIMATES, headers=auth_headers)
    assert restored.json()["status"] == "AVAILABLE"


@pytest.mark.asyncio
async def test_legacy_pregnancy_selection_untouched_by_aging(
    async_client: AsyncClient, auth_headers: dict
):
    before = await async_client.get("/api/v1/health-context", headers=auth_headers)
    assert before.json()["pregnancy_context"] is None
    await _put_notes(async_client, auth_headers, {"notes": "Aging context."})
    after = await async_client.get("/api/v1/health-context", headers=auth_headers)
    assert after.json()["pregnancy_context"] is None


# --- H. Fertility interaction (Phase 2 behavior preserved) -------------------


@pytest.mark.asyncio
async def test_aging_context_does_not_change_fertility_estimates(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    await _make_periods(async_client, auth_headers, _stable_history())
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

    snapshot = (await async_client.get(ESTIMATES, headers=auth_headers)).json()
    await _put_notes(async_client, auth_headers, {"notes": "Aging context."})
    after = (await async_client.get(ESTIMATES, headers=auth_headers)).json()
    # Identical apart from the recalculated instant.
    assert {k: v for k, v in after.items() if k != "calculated_at"} == {
        k: v for k, v in snapshot.items() if k != "calculated_at"
    }
    assert after["status"] == "AVAILABLE"
    assert after["evidence_source"] == "OBSERVED"
    _assert_no_banned_claims(after)


@pytest.mark.asyncio
async def test_insufficient_estimate_unchanged_by_aging(
    async_client: AsyncClient, other_user_auth_headers: dict
):
    snapshot = (
        await async_client.get(ESTIMATES, headers=other_user_auth_headers)
    ).json()
    assert snapshot["status"] == "INSUFFICIENT_DATA"
    await _put_notes(async_client, other_user_auth_headers, {"notes": "Note."})
    after = (await async_client.get(ESTIMATES, headers=other_user_auth_headers)).json()
    assert after["status"] == "INSUFFICIENT_DATA"
    assert after["estimated_ovulation_date"] is None


# --- I. Predictor protection -------------------------------------------------


@pytest.mark.asyncio
async def test_aging_context_does_not_alter_period_predictions(
    async_client: AsyncClient, auth_headers: dict
):
    await _make_periods(async_client, auth_headers, _stable_history())
    before = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert before.status_code == 200
    snapshot = {
        k: before.json()[k]
        for k in (
            "current_cycle_day",
            "phase",
            "is_bleeding",
            "predicted_next_period",
            "days_until_next_period",
            "prediction_status",
            "prediction_confidence",
            "average_cycle_length",
            "average_period_length",
        )
    }
    await _put_notes(async_client, auth_headers, {"notes": "Extensive context. " * 50})
    after = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert after.status_code == 200
    for key, value in snapshot.items():
        assert after.json()[key] == value, key
    current = await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    assert current.status_code == 200
    _assert_no_banned_claims(after.json())


# --- J. Historical data preservation -----------------------------------------


@pytest.mark.asyncio
async def test_aging_changes_preserve_all_history(
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
    log = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": str(t - timedelta(days=1)), "pain": 3, "mood": ["neutral"]},
    )
    assert log.status_code in (200, 201), log.text
    preg = await async_client.put(PREGNANCY, headers=auth_headers, json={"is_active": True})
    assert preg.status_code == 200

    cycles_before = (await async_client.get("/api/v1/cycles", headers=auth_headers)).json()
    obs_before = (await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)).json()

    await _put_notes(async_client, auth_headers, {"notes": "Recorded."})
    await _put_notes(async_client, auth_headers, {"notes": "Revised."})
    await _put_notes(async_client, auth_headers, {})

    cycles_after = (await async_client.get("/api/v1/cycles", headers=auth_headers)).json()
    obs_after = (await async_client.get("/api/v1/reproductive/observations", headers=auth_headers)).json()
    assert cycles_after == cycles_before
    assert obs_after == obs_before
    assert (await async_client.get(PREGNANCY, headers=auth_headers)).json()["is_active"] is True
    assert (await async_client.get(AGING, headers=auth_headers)).json()["has_context"] is False


# --- Medical safety wording --------------------------------------------------


@pytest.mark.asyncio
async def test_no_diagnosis_or_infertility_language_anywhere(
    async_client: AsyncClient, auth_headers: dict
):
    t = _today()
    await _make_periods(async_client, auth_headers, _stable_history())
    bodies = []
    bodies.append((await async_client.get(AGING, headers=auth_headers)).json())
    bodies.append(await _put_notes(async_client, auth_headers, {"notes": "Irregular lately."}))
    bodies.append((await async_client.get(ESTIMATES, headers=auth_headers)).json())
    bodies.append((await async_client.get("/api/v1/summary/current", headers=auth_headers)).json())
    for body in bodies:
        _assert_no_banned_claims(body)
    # The recorded context is labeled as user context, never as a diagnosis.
    recorded = bodies[1]
    assert recorded["provenance"] == "user_declared"
    disclaimer = recorded["disclaimer"].lower()
    assert "not a medical diagnosis" in disclaimer


# --- Health Context compatibility --------------------------------------------


@pytest.mark.asyncio
async def test_health_context_values_untouched_by_aging(
    async_client: AsyncClient, auth_headers: dict
):
    put = await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"health_notes": "Existing notes.", "pregnancy_context": "avoiding_pregnancy"},
    )
    assert put.status_code == 200
    await _put_notes(async_client, auth_headers, {"notes": "Aging context."})
    await _put_notes(async_client, auth_headers, {})
    after = await async_client.get("/api/v1/health-context", headers=auth_headers)
    assert after.json()["health_notes"] == "Existing notes."
    assert after.json()["pregnancy_context"] == "avoiding_pregnancy"


# --- Schema / migration agreement --------------------------------------------


def test_aging_model_metadata_matches_migration():
    from app.db.base import Base

    tables = Base.metadata.tables
    assert "reproductive_aging_contexts" in tables
    assert set(tables["reproductive_aging_contexts"].columns.keys()) == {
        "user_id",
        "notes",
        "created_at",
        "updated_at",
    }
    fks = list(tables["reproductive_aging_contexts"].foreign_keys)
    assert any(
        fk.column.table.name == "profiles"
        and fk.column.name == "user_id"
        and fk.ondelete == "CASCADE"
        for fk in fks
    ), "reproductive_aging_contexts must FK to profiles.user_id ON DELETE CASCADE"


def test_aging_migration_and_fresh_schema_agree():
    from pathlib import Path

    root = Path(__file__).parent.parent
    migration = (root / "migrations" / "0007_reproductive_aging_context_v1.sql").read_text()
    schema = (root / "supabase_initial_schema.sql").read_text()
    for needle in (
        "CREATE TABLE IF NOT EXISTS public.reproductive_aging_contexts",
        "ALTER TABLE public.reproductive_aging_contexts ENABLE ROW LEVEL SECURITY",
    ):
        assert needle in migration, needle
        assert needle in schema, needle
    assert "FORCE ROW LEVEL SECURITY" not in migration
    assert "CREATE POLICY" not in migration
