from datetime import date, timedelta
import pytest
from httpx import AsyncClient


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
async def test_query_logs_date_range(async_client: AsyncClient, auth_headers: dict):
    # Log two consecutive days
    d1 = date.today() - timedelta(days=1)
    d2 = date.today()

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
