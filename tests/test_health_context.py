from datetime import date

import pytest
from httpx import AsyncClient

from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID


# --- Singleton context: sync-style upsert ------------------------------------


@pytest.mark.asyncio
async def test_health_context_get_defaults_when_unset(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.get("/api/v1/health-context", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == str(TEST_USER_ID)
    assert data["contraception_method"] is None
    assert data["contraception_note"] is None
    assert data["pregnancy_context"] is None
    assert data["health_notes"] is None


@pytest.mark.asyncio
async def test_health_context_put_full_replacement(
    async_client: AsyncClient, auth_headers: dict
):
    full = {
        "contraception_method": "copper_iud",
        "contraception_note": "Inserted Jan 2026",
        "pregnancy_context": "avoiding_pregnancy",
        "health_notes": "Migraines tend to cluster before bleeding.",
    }
    put_res = await async_client.put(
        "/api/v1/health-context", headers=auth_headers, json=full
    )
    assert put_res.status_code == 200
    assert put_res.json()["contraception_method"] == "copper_iud"
    assert put_res.json()["pregnancy_context"] == "avoiding_pregnancy"

    # Full replacement: omitted fields are cleared to null
    put2 = await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"pregnancy_context": "pregnant"},
    )
    assert put2.status_code == 200
    data2 = put2.json()
    assert data2["pregnancy_context"] == "pregnant"
    assert data2["contraception_method"] is None
    assert data2["contraception_note"] is None
    assert data2["health_notes"] is None


@pytest.mark.asyncio
async def test_health_context_patch_partial_and_null_clearing(
    async_client: AsyncClient, auth_headers: dict
):
    await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={
            "contraception_method": "implant",
            "contraception_note": "Nexplanon",
            "pregnancy_context": "avoiding_pregnancy",
            "health_notes": "Some notes",
        },
    )

    # Partial update leaves unmentioned fields intact
    patch_res = await async_client.patch(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"pregnancy_context": "trying_to_conceive"},
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert patched["pregnancy_context"] == "trying_to_conceive"
    assert patched["contraception_method"] == "implant"
    assert patched["contraception_note"] == "Nexplanon"

    # Explicit null clears
    clear_res = await async_client.patch(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"contraception_note": None, "health_notes": None},
    )
    assert clear_res.status_code == 200
    cleared = clear_res.json()
    assert cleared["contraception_note"] is None
    assert cleared["health_notes"] is None
    assert cleared["contraception_method"] == "implant"


@pytest.mark.asyncio
async def test_health_context_rejects_invalid_enums(
    async_client: AsyncClient, auth_headers: dict
):
    bad_method = await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"contraception_method": "moon_crystal"},
    )
    assert bad_method.status_code == 422

    bad_pregnancy = await async_client.patch(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"pregnancy_context": "super_fertile"},
    )
    assert bad_pregnancy.status_code == 422


@pytest.mark.asyncio
async def test_health_context_free_text_limits(
    async_client: AsyncClient, auth_headers: dict
):
    # Stored verbatim up to the limit
    ok = await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"health_notes": "PCOS diagnosed 2023; metformin as needed."},
    )
    assert ok.status_code == 200
    assert ok.json()["health_notes"] == "PCOS diagnosed 2023; metformin as needed."

    # Beyond the limit is rejected, not truncated
    too_long = await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"health_notes": "x" * 2001},
    )
    assert too_long.status_code == 422


@pytest.mark.asyncio
async def test_health_context_pregnancy_values_accepted(
    async_client: AsyncClient, auth_headers: dict
):
    for value in (
        "trying_to_conceive",
        "avoiding_pregnancy",
        "pregnant",
        "postpartum",
        "not_applicable",
        "prefer_not_to_say",
    ):
        res = await async_client.patch(
            "/api/v1/health-context",
            headers=auth_headers,
            json={"pregnancy_context": value},
        )
        assert res.status_code == 200, value
        assert res.json()["pregnancy_context"] == value


# --- Conditions ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_condition_lifecycle(async_client: AsyncClient, auth_headers: dict):
    # Create curated condition (optionals default)
    create_res = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "migraine"},
    )
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["condition_code"] == "migraine"
    assert created["custom_label"] is None
    assert created["note"] is None
    assert created["is_active"] is True
    assert created["user_id"] == str(TEST_USER_ID)
    cond_id = created["id"]

    # Duplicate curated code conflicts
    dup = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "migraine"},
    )
    assert dup.status_code == 409

    # 'other' entries with distinct labels coexist
    o1 = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "other", "custom_label": "Raynaud's"},
    )
    assert o1.status_code == 201
    o2 = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "other", "custom_label": "Eczema", "note": "Winter flares"},
    )
    assert o2.status_code == 201
    assert o2.json()["note"] == "Winter flares"

    # List shows all three
    list_res = await async_client.get(
        "/api/v1/health-context/conditions", headers=auth_headers
    )
    assert list_res.status_code == 200
    assert len(list_res.json()) == 3

    # Partial update: add note + deactivate
    patch_res = await async_client.patch(
        f"/api/v1/health-context/conditions/{cond_id}",
        headers=auth_headers,
        json={"note": "With aura", "is_active": False},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["note"] == "With aura"
    assert patch_res.json()["is_active"] is False
    assert patch_res.json()["condition_code"] == "migraine"

    # Clear note explicitly
    clear_res = await async_client.patch(
        f"/api/v1/health-context/conditions/{cond_id}",
        headers=auth_headers,
        json={"note": None},
    )
    assert clear_res.status_code == 200
    assert clear_res.json()["note"] is None

    # Delete
    del_res = await async_client.delete(
        f"/api/v1/health-context/conditions/{cond_id}", headers=auth_headers
    )
    assert del_res.status_code == 204

    list_after = await async_client.get(
        "/api/v1/health-context/conditions", headers=auth_headers
    )
    assert len(list_after.json()) == 2


@pytest.mark.asyncio
async def test_condition_label_contract(async_client: AsyncClient, auth_headers: dict):
    # 'other' without a label is rejected
    no_label = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "other"},
    )
    assert no_label.status_code == 422

    # Blank label is rejected
    blank = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "other", "custom_label": "   "},
    )
    assert blank.status_code == 422

    # Label on a curated code is rejected
    misplaced = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "pcos", "custom_label": "PCOS"},
    )
    assert misplaced.status_code == 422

    # Unknown code is rejected
    unknown = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "alien_parasite"},
    )
    assert unknown.status_code == 422

    # Switching a row to 'other' without a label is rejected
    created = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "anemia"},
    )
    bad_switch = await async_client.patch(
        f"/api/v1/health-context/conditions/{created.json()['id']}",
        headers=auth_headers,
        json={"condition_code": "other"},
    )
    assert bad_switch.status_code == 422


@pytest.mark.asyncio
async def test_condition_update_duplicate_conflicts(
    async_client: AsyncClient, auth_headers: dict
):
    r1 = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "pcos"},
    )
    r2 = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "endometriosis"},
    )
    clash = await async_client.patch(
        f"/api/v1/health-context/conditions/{r2.json()['id']}",
        headers=auth_headers,
        json={"condition_code": "pcos"},
    )
    assert clash.status_code == 409
    assert r1.json()["id"] != r2.json()["id"]


# --- Medications --------------------------------------------------------------


@pytest.mark.asyncio
async def test_medication_lifecycle(async_client: AsyncClient, auth_headers: dict):
    create_res = await async_client.post(
        "/api/v1/health-context/medications",
        headers=auth_headers,
        json={"name": "Iron supplement"},
    )
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["name"] == "Iron supplement"
    assert created["note"] is None
    assert created["is_active"] is True
    med_id = created["id"]

    # Blank names rejected
    blank = await async_client.post(
        "/api/v1/health-context/medications",
        headers=auth_headers,
        json={"name": "   "},
    )
    assert blank.status_code == 422

    patch_res = await async_client.patch(
        f"/api/v1/health-context/medications/{med_id}",
        headers=auth_headers,
        json={"note": "Every other day", "is_active": False},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["note"] == "Every other day"
    assert patch_res.json()["is_active"] is False
    assert patch_res.json()["name"] == "Iron supplement"

    del_res = await async_client.delete(
        f"/api/v1/health-context/medications/{med_id}", headers=auth_headers
    )
    assert del_res.status_code == 204

    list_res = await async_client.get(
        "/api/v1/health-context/medications", headers=auth_headers
    )
    assert list_res.json() == []


# --- Privacy / isolation ------------------------------------------------------


@pytest.mark.asyncio
async def test_health_context_unauthenticated_rejected(async_client: AsyncClient):
    assert (await async_client.get("/api/v1/health-context")).status_code == 401
    assert (
        await async_client.post(
            "/api/v1/health-context/conditions", json={"condition_code": "migraine"}
        )
    ).status_code == 401
    assert (
        await async_client.post(
            "/api/v1/health-context/medications", json={"name": "Iron"}
        )
    ).status_code == 401


@pytest.mark.asyncio
async def test_cross_user_health_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"pregnancy_context": "pregnant", "health_notes": "User 1 private notes"},
    )
    cond = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "pcos", "note": "User 1 private note"},
    )
    med = await async_client.post(
        "/api/v1/health-context/medications",
        headers=auth_headers,
        json={"name": "User 1 private med"},
    )

    # Other user sees defaults/empty, never user 1's data
    other_ctx = await async_client.get(
        "/api/v1/health-context", headers=other_user_auth_headers
    )
    assert other_ctx.json()["pregnancy_context"] is None
    assert other_ctx.json()["health_notes"] is None
    other_conds = await async_client.get(
        "/api/v1/health-context/conditions", headers=other_user_auth_headers
    )
    assert other_conds.json() == []
    other_meds = await async_client.get(
        "/api/v1/health-context/medications", headers=other_user_auth_headers
    )
    assert other_meds.json() == []

    # Other user cannot mutate user 1's rows by id
    cond_id = cond.json()["id"]
    med_id = med.json()["id"]
    assert (
        await async_client.patch(
            f"/api/v1/health-context/conditions/{cond_id}",
            headers=other_user_auth_headers,
            json={"note": "hijacked"},
        )
    ).status_code == 404
    assert (
        await async_client.delete(
            f"/api/v1/health-context/conditions/{cond_id}",
            headers=other_user_auth_headers,
        )
    ).status_code == 404
    assert (
        await async_client.patch(
            f"/api/v1/health-context/medications/{med_id}",
            headers=other_user_auth_headers,
            json={"note": "hijacked"},
        )
    ).status_code == 404
    assert (
        await async_client.delete(
            f"/api/v1/health-context/medications/{med_id}",
            headers=other_user_auth_headers,
        )
    ).status_code == 404

    # Owner's rows are untouched
    own_cond = await async_client.get(
        "/api/v1/health-context/conditions", headers=auth_headers
    )
    assert own_cond.json()[0]["note"] == "User 1 private note"


@pytest.mark.asyncio
async def test_client_supplied_user_id_is_ignored(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    # Extra user_id fields are not part of the contract and must not
    # redirect ownership: the row always belongs to the JWT subject.
    res = await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "migraine", "user_id": str(ANOTHER_USER_ID)},
    )
    assert res.status_code == 201
    assert res.json()["user_id"] == str(TEST_USER_ID)

    other_list = await async_client.get(
        "/api/v1/health-context/conditions", headers=other_user_auth_headers
    )
    assert other_list.json() == []


@pytest.mark.asyncio
async def test_profile_delete_cascades_health_data(
    async_client: AsyncClient, auth_headers: dict
):
    await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={"pregnancy_context": "postpartum"},
    )
    await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "thyroid_disorder"},
    )
    await async_client.post(
        "/api/v1/health-context/medications",
        headers=auth_headers,
        json={"name": "Levothyroxine"},
    )
    await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"birth_year": 1990, "birth_month": 4}
    )

    del_res = await async_client.delete("/api/v1/profile", headers=auth_headers)
    assert del_res.status_code == 204

    # Fresh profile has no DOB and no health data remains
    profile = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert profile.json()["birth_year"] is None
    assert profile.json()["birth_month"] is None
    ctx = await async_client.get("/api/v1/health-context", headers=auth_headers)
    assert ctx.json()["pregnancy_context"] is None
    conds = await async_client.get(
        "/api/v1/health-context/conditions", headers=auth_headers
    )
    assert conds.json() == []
    meds = await async_client.get(
        "/api/v1/health-context/medications", headers=auth_headers
    )
    assert meds.json() == []


# --- Profile DOB (month/year precision) ---------------------------------------


@pytest.mark.asyncio
async def test_profile_dob_lifecycle(async_client: AsyncClient, auth_headers: dict):
    set_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"birth_year": 1994, "birth_month": 7},
    )
    assert set_res.status_code == 200
    assert set_res.json()["birth_year"] == 1994
    assert set_res.json()["birth_month"] == 7

    # Partial update keeps the stored counterpart
    month_only = await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"birth_month": 8}
    )
    assert month_only.status_code == 200
    assert month_only.json()["birth_year"] == 1994
    assert month_only.json()["birth_month"] == 8

    # Explicit-null clearing of both at once
    clear = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"birth_year": None, "birth_month": None},
    )
    assert clear.status_code == 200
    assert clear.json()["birth_year"] is None
    assert clear.json()["birth_month"] is None


@pytest.mark.asyncio
async def test_profile_dob_validation(async_client: AsyncClient, auth_headers: dict):
    # Incomplete pair rejected
    year_only = await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"birth_year": 1990}
    )
    assert year_only.status_code == 422
    month_only = await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"birth_month": 5}
    )
    assert month_only.status_code == 422

    # Out-of-range month rejected
    bad_month = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"birth_year": 1990, "birth_month": 13},
    )
    assert bad_month.status_code == 422

    # Future year rejected
    future = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"birth_year": date.today().year + 1, "birth_month": 1},
    )
    assert future.status_code == 422

    # Clearing only one side of a stored pair is rejected
    await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"birth_year": 1988, "birth_month": 3},
    )
    half_clear = await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"birth_year": None}
    )
    assert half_clear.status_code == 422

    # Failed attempts leave no partial state
    profile = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert profile.json()["birth_year"] == 1988
    assert profile.json()["birth_month"] == 3


# --- Prediction boundary -------------------------------------------------------


@pytest.mark.asyncio
async def test_health_context_does_not_alter_predictions(
    async_client: AsyncClient, auth_headers: dict
):
    from datetime import timedelta

    today = date.today()
    starts = [today - timedelta(days=90), today - timedelta(days=62), today - timedelta(days=33)]
    for s in starts:
        r = await async_client.post(
            "/api/v1/cycles",
            headers=auth_headers,
            json={"period_start": str(s), "period_end": str(s + timedelta(days=4))},
        )
        assert r.status_code == 201

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

    # Add extensive health context: predictions must not move
    await async_client.put(
        "/api/v1/health-context",
        headers=auth_headers,
        json={
            "contraception_method": "combined_pill",
            "pregnancy_context": "avoiding_pregnancy",
            "health_notes": "PCOS diagnosed 2022.",
        },
    )
    await async_client.post(
        "/api/v1/health-context/conditions",
        headers=auth_headers,
        json={"condition_code": "pcos"},
    )
    await async_client.post(
        "/api/v1/health-context/medications",
        headers=auth_headers,
        json={"name": "Combined pill"},
    )
    await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"birth_year": 1995, "birth_month": 6}
    )

    after = await async_client.get("/api/v1/summary/current", headers=auth_headers)
    assert after.status_code == 200
    for key, value in snapshot.items():
        assert after.json()[key] == value, key


# --- Model/migration consistency ------------------------------------------------


def test_health_model_metadata_matches_migration():
    from app.db.base import Base

    tables = Base.metadata.tables
    for name in ("health_contexts", "health_conditions", "medications"):
        assert name in tables, f"missing table {name}"

    assert set(tables["health_contexts"].columns.keys()) == {
        "user_id",
        "contraception_method",
        "contraception_note",
        "pregnancy_context",
        "health_notes",
        "created_at",
        "updated_at",
    }
    assert set(tables["health_conditions"].columns.keys()) == {
        "id",
        "user_id",
        "condition_code",
        "custom_label",
        "note",
        "is_active",
        "created_at",
        "updated_at",
    }
    assert set(tables["medications"].columns.keys()) == {
        "id",
        "user_id",
        "name",
        "note",
        "is_active",
        "created_at",
        "updated_at",
    }
    profile_cols = set(tables["profiles"].columns.keys())
    assert {"birth_year", "birth_month"} <= profile_cols

    # Every health table references the profile with cascade delete
    for table_name in ("health_contexts", "health_conditions", "medications"):
        fks = list(tables[table_name].foreign_keys)
        assert any(
            fk.column.table.name == "profiles"
            and fk.column.name == "user_id"
            and fk.ondelete == "CASCADE"
            for fk in fks
        ), f"{table_name} must FK to profiles.user_id ON DELETE CASCADE"
