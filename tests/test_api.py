from datetime import date, timedelta
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_auth_sync_profile(async_client: AsyncClient, auth_headers: dict):
    response = await async_client.post(
        "/api/v1/auth/sync-profile",
        headers=auth_headers,
        json={"cycle_length_avg": 29, "period_length_avg": 5},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["cycle_length_avg"] == 29
    assert data["period_length_avg"] == 5
    assert data["sensitivity_index"] == 1.0


@pytest.mark.asyncio
async def test_cycle_lifecycle(async_client: AsyncClient, auth_headers: dict):
    # 1. Check current before any cycle
    curr_res = await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    assert curr_res.status_code == 200
    assert curr_res.json()["active_cycle"] is None

    # 2. Start a cycle
    start_date_str = str(date.today() - timedelta(days=5))
    start_res = await async_client.post(
        "/api/v1/cycles/start",
        headers=auth_headers,
        json={"start_date": start_date_str},
    )
    assert start_res.status_code == 201
    cycle_data = start_res.json()
    cycle_id = cycle_data["id"]
    assert cycle_data["is_active"] is True
    assert cycle_data["predicted_ovulation"] is not None

    # 3. Check current status
    curr_res2 = await async_client.get("/api/v1/cycles/current", headers=auth_headers)
    assert curr_res2.status_code == 200
    status_data = curr_res2.json()
    assert status_data["active_cycle"] is not None
    assert status_data["current_cycle_day"] == 6

    # 4. End cycle
    end_date_str = str(date.today())
    end_res = await async_client.put(
        f"/api/v1/cycles/{cycle_id}/end",
        headers=auth_headers,
        json={"end_date": end_date_str},
    )
    assert end_res.status_code == 200
    assert end_res.json()["is_active"] is False


@pytest.mark.asyncio
async def test_daily_logs_upsert_and_history(async_client: AsyncClient, auth_headers: dict):
    today_str = str(date.today())
    payload = {
        "log_date": today_str,
        "cramp_severity": 6,
        "flow_intensity": "medium",
        "mood": "anxious",
        "symptoms": ["headache", "bloating", "lower_back_pain"],
        "notes": "Feeling uncomfortable in the afternoon",
    }
    
    # Create log
    res = await async_client.post("/api/v1/logs/daily", headers=auth_headers, json=payload)
    assert res.status_code == 200
    log_data = res.json()
    assert log_data["cramp_severity"] == 6
    assert "bloating" in log_data["symptoms"]

    # Upsert same day with updated severity
    payload["cramp_severity"] = 7
    res_update = await async_client.post("/api/v1/logs/daily", headers=auth_headers, json=payload)
    assert res_update.status_code == 200
    assert res_update.json()["cramp_severity"] == 7

    # Fetch history
    history_res = await async_client.get("/api/v1/logs/history?days=30", headers=auth_headers)
    assert history_res.status_code == 200
    entries = history_res.json()
    assert len(entries) >= 1
    assert entries[0]["cramp_severity"] == 7


@pytest.mark.asyncio
async def test_therapy_recommend_and_session(async_client: AsyncClient, auth_headers: dict):
    # Log today's cramp severity as 7 first
    await async_client.post(
        "/api/v1/logs/daily",
        headers=auth_headers,
        json={
            "cramp_severity": 7,
            "flow_intensity": "heavy",
            "mood": "fatigued",
            "symptoms": ["cramps"],
        },
    )

    # 1. Recommendation engine using daily log
    rec_res = await async_client.post("/api/v1/therapy/recommend", headers=auth_headers, json={})
    assert rec_res.status_code == 200
    rec_data = rec_res.json()
    assert rec_data["cramp_severity"] == 7
    assert rec_data["target_temp_celsius"] == 39.5
    assert rec_data["vibration_mode"] == "wave"
    assert rec_data["vibration_intensity"] == 70

    # 2. Recommendation engine with override
    rec_res_override = await async_client.post(
        "/api/v1/therapy/recommend",
        headers=auth_headers,
        json={"cramp_severity": 2},
    )
    assert rec_res_override.status_code == 200
    assert rec_res_override.json()["target_temp_celsius"] == 37.0
    assert rec_res_override.json()["vibration_mode"] == "pulse"

    # 3. Log a therapy session
    session_res = await async_client.post(
        "/api/v1/therapy/session",
        headers=auth_headers,
        json={
            "target_temp_celsius": 39.5,
            "vibration_mode": "wave",
            "vibration_intensity": 70,
            "duration_minutes": 25,
            "pre_cramp_score": 7,
        },
    )
    assert session_res.status_code == 201
    session_data = session_res.json()
    session_id = session_data["id"]
    assert session_data["pre_cramp_score"] == 7
    assert session_data["post_relief_score"] is None

    # 4. Patch feedback with insufficient_relief (should bump sensitivity)
    feedback_res = await async_client.patch(
        f"/api/v1/therapy/session/{session_id}/feedback",
        headers=auth_headers,
        json={
            "post_relief_score": 4,
            "feedback_tag": "insufficient_relief",
        },
    )
    assert feedback_res.status_code == 200
    assert feedback_res.json()["feedback_tag"] == "insufficient_relief"
    assert feedback_res.json()["post_relief_score"] == 4
