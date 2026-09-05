import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_device_lifecycle(async_client: AsyncClient, auth_headers: dict):
    # 1. Register device
    dev_payload = {
        "device_identifier": "AA:BB:CC:DD:EE:FF",
        "name": "MenoMate Band",
        "firmware_version": "v1.2.0",
    }
    reg_res = await async_client.post("/api/v1/devices", headers=auth_headers, json=dev_payload)
    assert reg_res.status_code == 201
    device_data = reg_res.json()
    device_id = device_data["id"]
    assert device_data["name"] == "MenoMate Band"

    # 2. List devices
    list_res = await async_client.get("/api/v1/devices", headers=auth_headers)
    assert list_res.status_code == 200
    devices = list_res.json()
    assert len(devices) == 1
    assert devices[0]["id"] == device_id

    # 3. Unpair device
    del_res = await async_client.delete(f"/api/v1/devices/{device_id}", headers=auth_headers)
    assert del_res.status_code == 204

    # 4. Confirm unpairing
    list_res2 = await async_client.get("/api/v1/devices", headers=auth_headers)
    assert len(list_res2.json()) == 0


@pytest.mark.asyncio
async def test_therapy_recommendation_safety_clamp(async_client: AsyncClient, auth_headers: dict):
    # Severity 0 -> hardware off
    rec0 = await async_client.post("/api/v1/therapy/recommend", headers=auth_headers, json={"pain_score": 0})
    assert rec0.status_code == 200
    assert rec0.json()["target_temperature_c"] == 0.0
    assert rec0.json()["vibration_mode"] == "off"

    # Severity 6 -> moderate heat
    rec6 = await async_client.post("/api/v1/therapy/recommend", headers=auth_headers, json={"pain_score": 6})
    assert rec6.status_code == 200
    assert rec6.json()["target_temperature_c"] == 39.5
    assert rec6.json()["vibration_mode"] == "wave"

    # Severity 10 -> strict 44.0°C ceiling
    rec10 = await async_client.post("/api/v1/therapy/recommend", headers=auth_headers, json={"pain_score": 10})
    assert rec10.status_code == 200
    assert rec10.json()["target_temperature_c"] <= 44.0
    assert rec10.json()["target_temperature_c"] == 42.0


@pytest.mark.asyncio
async def test_therapy_session_and_feedback_tuning(async_client: AsyncClient, auth_headers: dict):
    # 1. Log session
    session_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={
            "mode": "adaptive",
            "target_temperature_c": 40.0,
            "vibration_intensity": 70,
            "vibration_mode": "wave",
            "pain_before": 7,
        },
    )
    assert session_res.status_code == 201
    s_id = session_res.json()["id"]

    # 2. Patch feedback tag: insufficient_relief (should bump sensitivity by +0.05)
    patch_res = await async_client.patch(
        f"/api/v1/therapy/sessions/{s_id}",
        headers=auth_headers,
        json={"pain_after": 4, "feedback": "insufficient_relief"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["feedback"] == "insufficient_relief"

    # 3. Verify user profile sensitivity index was updated to 1.05
    prof_res = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert prof_res.status_code == 200
    assert prof_res.json()["sensitivity_index"] == 1.05
