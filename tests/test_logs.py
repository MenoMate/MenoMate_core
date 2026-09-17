from datetime import date, timedelta
import pytest
from httpx import AsyncClient

from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID


@pytest.mark.asyncio
async def test_get_supported_symptoms(async_client: AsyncClient):
    res = await async_client.get("/api/v1/symptoms")
    assert res.status_code == 200
    symptoms = res.json()
    assert len(symptoms) >= 10
    ids = [s["id"] for s in symptoms]
    assert "cramps" in ids
    assert "nausea" in ids
    assert "back_pain" in ids


@pytest.mark.asyncio
async def test_create_and_upsert_daily_log_with_symptoms(async_client: AsyncClient, auth_headers: dict):
    today = str(date.today())
    payload = {
        "log_date": today,
        "pain": 6,
        "mood": ["anxious"],
        "discharge": "creamy",
        "flow": "medium",
        "notes": "Afternoon cramps",
        "symptoms": [
            {"symptom_type": "cramps", "severity": 7},
            {"symptom_type": "headache", "severity": 4},
        ],
    }

    # 1. Create log
    res = await async_client.post("/api/v1/logs", headers=auth_headers, json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["pain"] == 6
    assert data["mood"] == ["anxious"]
    assert data["discharge"] == "creamy"
    assert len(data["symptoms"]) == 2

    # 2. Get log by date
    get_res = await async_client.get(f"/api/v1/logs/{today}", headers=auth_headers)
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["pain"] == 6
    assert get_data["notes"] == "Afternoon cramps"
    assert len(get_data["symptoms"]) == 2

    # 3. Upsert (update) same day with changed symptoms and flow
    payload["pain"] = 4
    payload["flow"] = "light"
    payload["symptoms"] = [
        {"symptom_type": "cramps", "severity": 3},
        {"symptom_type": "low_energy", "severity": 6},
    ]

    update_res = await async_client.post("/api/v1/logs", headers=auth_headers, json=payload)
    assert update_res.status_code == 200
    up_data = update_res.json()
    assert up_data["pain"] == 4
    assert up_data["flow"] == "light"
    assert len(up_data["symptoms"]) == 2
    types = [s["symptom_type"] for s in up_data["symptoms"]]
    assert "low_energy" in types
    assert "headache" not in types


@pytest.mark.asyncio
async def test_patch_log_clear_optional_field(async_client: AsyncClient, auth_headers: dict):
    # Create log with notes and mood
    today = str(date.today())
    create_res = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": today, "pain": 3, "mood": ["calm"], "notes": "Felt good today"},
    )
    assert create_res.status_code == 200
    log_id = create_res.json()["id"]
    assert create_res.json()["notes"] == "Felt good today"
    assert create_res.json()["mood"] == ["calm"]

    # Explicitly clear notes and mood by supplying null
    patch_res = await async_client.patch(
        f"/api/v1/logs/{log_id}",
        headers=auth_headers,
        json={"notes": None, "mood": None},
    )
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["notes"] is None
    assert updated["mood"] is None
    assert updated["pain"] == 3  # Unaltered


@pytest.mark.asyncio
async def test_log_validation_constraints(async_client: AsyncClient, auth_headers: dict):
    # Invalid pain (> 10)
    res_pain = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"pain": 11},
    )
    assert res_pain.status_code == 422

    # Invalid symptom severity (> 10)
    res_sev = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"symptoms": [{"symptom_type": "cramps", "severity": 15}]},
    )
    assert res_sev.status_code == 422

    # Unsupported symptom_type
    res_type = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"symptoms": [{"symptom_type": "alien_abduction", "severity": 5}]},
    )
    assert res_type.status_code == 422


@pytest.mark.asyncio
async def test_cross_user_log_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    target_date = str(date.today() - timedelta(days=5))
    # User 1 creates a log
    await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": target_date, "pain": 8, "notes": "User 1 confidential notes"},
    )

    # User 2 tries to fetch log for that date
    res = await async_client.get(f"/api/v1/logs/{target_date}", headers=other_user_auth_headers)
    assert res.status_code == 200
    assert res.json() is None  # User 2 has no log on that date

    # User 2 queries logs
    list_res = await async_client.get("/api/v1/logs", headers=other_user_auth_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) == 0


@pytest.mark.asyncio
async def test_query_logs_date_range(async_client: AsyncClient, auth_headers: dict):
    d1 = date.today() - timedelta(days=2)
    d2 = date.today() - timedelta(days=1)

    await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": str(d1), "pain": 2, "symptoms": []},
    )
    await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": str(d2), "pain": 5, "symptoms": []},
    )

    res = await async_client.get(
        f"/api/v1/logs?start_date={d1}&end_date={d2}",
        headers=auth_headers,
    )
    assert res.status_code == 200
    logs = res.json()
    assert len(logs) >= 2


@pytest.mark.asyncio
async def test_query_logs_inverted_date_range_rejected(async_client: AsyncClient, auth_headers: dict):
    d1 = date.today() - timedelta(days=2)
    d2 = date.today() - timedelta(days=5)

    # Inverted: start_date (2 days ago) > end_date (5 days ago)
    res = await async_client.get(
        f"/api/v1/logs?start_date={d1}&end_date={d2}",
        headers=auth_headers,
    )
    assert res.status_code == 422
    assert "start_date cannot be after end_date" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Structured logging truthfulness: nullable pain, severity, discharge,
# catalog stability, pain-average correction.
# ---------------------------------------------------------------------------

EXPECTED_SYMPTOM_IDS = {
    "cramps", "headache", "back_pain", "nausea", "bloating", "low_energy",
    "breast_tenderness", "acne", "sleep_difficulty", "appetite_change",
    "dizziness",
}


@pytest.mark.asyncio
async def test_symptom_catalog_ids_stable(async_client: AsyncClient):
    """Pins the canonical catalog: mobile mirrors these ids, so any
    removal/rename here must update the mobile list in the same change."""
    res = await async_client.get("/api/v1/symptoms")
    assert res.status_code == 200
    assert {s["id"] for s in res.json()} == EXPECTED_SYMPTOM_IDS


@pytest.mark.asyncio
async def test_symptom_payload_validation(async_client: AsyncClient, auth_headers: dict):
    day = date.today() - timedelta(days=1)
    bad_id = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(day), "pain": 3,
              "symptoms": [{"symptom_type": "not_a_symptom", "severity": 5}]},
    )
    assert bad_id.status_code == 422
    bad_sev = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(day), "pain": 3,
              "symptoms": [{"symptom_type": "cramps", "severity": 11}]},
    )
    assert bad_sev.status_code == 422


@pytest.mark.asyncio
async def test_symptom_severity_and_discharge_round_trip(
    async_client: AsyncClient, auth_headers: dict
):
    day = date.today() - timedelta(days=1)
    res = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={
            "log_date": str(day),
            "pain": 6,
            "mood": ["tired"],
            "flow": "light",
            "discharge": "creamy",
            "symptoms": [
                {"symptom_type": "cramps", "severity": 6},
                {"symptom_type": "headache", "severity": 3},
            ],
        },
    )
    assert res.status_code in (200, 201), res.text
    body = res.json()
    assert body["discharge"] == "creamy"
    assert {s["symptom_type"]: s["severity"] for s in body["symptoms"]} == {
        "cramps": 6, "headache": 3,
    }
    assert body["mood"] == ["tired"]

    fetched = await async_client.get(f"/api/v1/logs/{day}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["symptoms"] == body["symptoms"]
    assert fetched.json()["discharge"] == "creamy"


@pytest.mark.asyncio
async def test_pain_null_vs_zero_semantics(async_client: AsyncClient, auth_headers: dict):
    d_null = date.today() - timedelta(days=3)
    d_zero = date.today() - timedelta(days=2)

    omitted = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(d_null), "mood": ["calm"]},
    )
    assert omitted.status_code in (200, 201)
    assert omitted.json()["pain"] is None

    explicit = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(d_zero), "pain": 0, "mood": ["calm"]},
    )
    assert explicit.status_code in (200, 201)
    assert explicit.json()["pain"] == 0

    get_null = await async_client.get(f"/api/v1/logs/{d_null}", headers=auth_headers)
    assert get_null.json()["pain"] is None
    get_zero = await async_client.get(f"/api/v1/logs/{d_zero}", headers=auth_headers)
    assert get_zero.json()["pain"] == 0


@pytest.mark.asyncio
async def test_recent_pain_avg_excludes_unset(
    async_client: AsyncClient, auth_headers: dict, db_session
):
    from sqlalchemy import select
    from app.models.daily_log import DailyLog
    from app.services.summary import get_current_cycle_summary
    from tests.conftest import TEST_USER_ID

    await async_client.post(
        "/api/v1/onboarding/complete", headers=auth_headers,
        json={
            "name": "Pain Avg",
            "last_period_start": str(date.today() - timedelta(days=5)),
            "last_period_end": str(date.today() - timedelta(days=2)),
        },
    )
    await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(date.today() - timedelta(days=3)), "mood": ["calm"]},
    )
    await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(date.today() - timedelta(days=2)), "pain": 6},
    )
    await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(date.today() - timedelta(days=1)), "pain": 0},
    )
    summary = await get_current_cycle_summary(db_session, TEST_USER_ID)
    assert summary["recent_pain_avg"] == 3.0

    rows = (
        await db_session.execute(select(DailyLog).where(DailyLog.user_id == TEST_USER_ID))
    ).scalars().all()
    assert {r.pain for r in rows} == {None, 6, 0}


# ---------------------------------------------------------------------------
# Multi-select mood + qualitative discharge vocabulary.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mood_multi_round_trip(async_client: AsyncClient, auth_headers: dict):
    day = date.today() - timedelta(days=1)
    res = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(day), "mood": ["happy", "calm", "happy"]},
    )
    assert res.status_code in (200, 201), res.text
    # Duplicates collapse, order preserved.
    assert res.json()["mood"] == ["happy", "calm"]

    fetched = await async_client.get(f"/api/v1/logs/{day}", headers=auth_headers)
    assert fetched.json()["mood"] == ["happy", "calm"]


@pytest.mark.asyncio
async def test_mood_empty_list_means_unset(async_client: AsyncClient, auth_headers: dict):
    day = date.today() - timedelta(days=1)
    res = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(day), "mood": []},
    )
    assert res.status_code in (200, 201)
    assert res.json()["mood"] is None


@pytest.mark.asyncio
async def test_mood_invalid_item_rejected(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(date.today() - timedelta(days=1)), "mood": ["calm", "ecstatic_joy"]},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_discharge_vocabulary_accepted(async_client: AsyncClient, auth_headers: dict):
    for i, value in enumerate(["sticky", "creamy", "watery", "slippery"]):
        day = date.today() - timedelta(days=1 + i)
        res = await async_client.post(
            "/api/v1/logs", headers=auth_headers,
            json={"log_date": str(day), "discharge": value},
        )
        assert res.status_code in (200, 201), (value, res.text)
        assert res.json()["discharge"] == value


@pytest.mark.asyncio
async def test_discharge_legacy_values_rejected_on_write(
    async_client: AsyncClient, auth_headers: dict
):
    for legacy in ["none", "light", "moderate", "heavy"]:
        res = await async_client.post(
            "/api/v1/logs", headers=auth_headers,
            json={"log_date": str(date.today() - timedelta(days=1)), "discharge": legacy},
        )
        assert res.status_code == 422, legacy


def test_decode_moods_tolerates_legacy_shapes():
    from app.schemas.daily_log import decode_moods

    assert decode_moods(None) is None
    assert decode_moods('["happy", "calm"]') == ["happy", "calm"]
    assert decode_moods("happy") == ["happy"]
    assert decode_moods([]) is None
    assert decode_moods("") is None


@pytest.mark.asyncio
async def test_flow_absent_means_unset(async_client: AsyncClient, auth_headers: dict):
    day = date.today() - timedelta(days=1)
    res = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(day), "pain": 2},
    )
    assert res.status_code in (200, 201)
    assert res.json()["flow"] is None
    assert res.json()["discharge"] is None
