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
        "mood": "anxious",
        "discharge": "moderate",
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
    assert data["mood"] == "anxious"
    assert data["discharge"] == "moderate"
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
        json={"log_date": today, "pain": 3, "mood": "calm", "notes": "Felt good today"},
    )
    assert create_res.status_code == 200
    log_id = create_res.json()["id"]
    assert create_res.json()["notes"] == "Felt good today"
    assert create_res.json()["mood"] == "calm"

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
