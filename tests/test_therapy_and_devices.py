import pytest
from httpx import AsyncClient

from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID


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
async def test_cross_user_device_and_session_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    # User 1 registers device
    reg_res = await async_client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={"device_identifier": "11:22:33:44:55:66", "name": "User 1 Band"},
    )
    assert reg_res.status_code == 201
    u1_device_id = reg_res.json()["id"]

    # User 2 lists devices -> cannot see User 1's device
    u2_devices = await async_client.get("/api/v1/devices", headers=other_user_auth_headers)
    assert u2_devices.status_code == 200
    assert len(u2_devices.json()) == 0

    # User 2 cannot unpair User 1's device
    u2_del = await async_client.delete(f"/api/v1/devices/{u1_device_id}", headers=other_user_auth_headers)
    assert u2_del.status_code == 404

    # User 1 creates therapy session
    s_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"mode": "standard", "target_temperature_c": 39.0, "vibration_intensity": 50},
    )
    assert s_res.status_code == 201
    u1_session_id = s_res.json()["id"]

    # User 2 lists sessions -> empty
    u2_sessions = await async_client.get("/api/v1/therapy/sessions", headers=other_user_auth_headers)
    assert u2_sessions.status_code == 200
    assert len(u2_sessions.json()) == 0

    # User 2 cannot patch User 1's session
    u2_patch = await async_client.patch(
        f"/api/v1/therapy/sessions/{u1_session_id}",
        headers=other_user_auth_headers,
        json={"pain_after": 1},
    )
    assert u2_patch.status_code == 404


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


@pytest.mark.asyncio
async def test_therapy_device_ownership(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    # 1. User A creates Device A
    dev_res = await async_client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={"device_identifier": "AA:11:22:33:44:55", "name": "User A Band"},
    )
    assert dev_res.status_code == 201
    device_a_id = dev_res.json()["id"]

    # 2. User B attempts to create therapy session with Device A
    bad_sess_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=other_user_auth_headers,
        json={
            "device_id": device_a_id,
            "mode": "standard",
            "target_temperature_c": 38.0,
        },
    )
    assert bad_sess_res.status_code == 400
    assert "not owned by authenticated user" in bad_sess_res.json()["detail"]

    # 3. Verify User B has 0 sessions created
    user_b_sessions = await async_client.get("/api/v1/therapy/sessions", headers=other_user_auth_headers)
    assert user_b_sessions.status_code == 200
    assert len(user_b_sessions.json()) == 0


@pytest.mark.asyncio
async def test_therapy_feedback_no_double_application_and_controlled_values(
    async_client: AsyncClient, auth_headers: dict
):
    # Reset profile sensitivity to 1.0
    await async_client.patch("/api/v1/profile", headers=auth_headers, json={"sensitivity_index": 1.0})

    # Create session with no initial feedback
    s_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"mode": "standard", "target_temperature_c": 39.0},
    )
    assert s_res.status_code == 201
    s_id = s_res.json()["id"]

    # First feedback PATCH -> bumps sensitivity
    prof_before = await async_client.get("/api/v1/profile", headers=auth_headers)
    initial_sens = prof_before.json()["sensitivity_index"]

    p1 = await async_client.patch(
        f"/api/v1/therapy/sessions/{s_id}",
        headers=auth_headers,
        json={"feedback": "insufficient_relief"},
    )
    assert p1.status_code == 200
    prof1 = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert round(prof1.json()["sensitivity_index"], 2) == round(initial_sens + 0.05, 2)

    # Repeated identical feedback PATCH on the same session -> idempotent no-op 200, does NOT bump sensitivity again
    p2 = await async_client.patch(
        f"/api/v1/therapy/sessions/{s_id}",
        headers=auth_headers,
        json={"feedback": "insufficient_relief"},
    )
    assert p2.status_code == 200
    prof2 = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert prof2.json()["sensitivity_index"] == prof1.json()["sensitivity_index"]

    # Changing feedback to a different value on the same session -> rejected with 409 Conflict (immutable)
    p_conflict = await async_client.patch(
        f"/api/v1/therapy/sessions/{s_id}",
        headers=auth_headers,
        json={"feedback": "too_hot"},
    )
    assert p_conflict.status_code == 409
    assert "immutable" in p_conflict.json()["detail"].lower()

    # Invalid feedback string must be rejected with 422
    p_invalid = await async_client.patch(
        f"/api/v1/therapy/sessions/{s_id}",
        headers=auth_headers,
        json={"feedback": "unsupported_feedback_value"},
    )
    assert p_invalid.status_code == 422


@pytest.mark.asyncio
async def test_therapy_feedback_concurrent_requests_cannot_double_apply(
    async_client: AsyncClient, auth_headers: dict
):
    """
    Verifies that concurrent feedback requests against the same therapy session
    cannot double-apply sensitivity adjustments under concurrency.
    """
    import asyncio

    # 1. Reset profile sensitivity to 1.00
    await async_client.patch("/api/v1/profile", headers=auth_headers, json={"sensitivity_index": 1.0})

    # 2. Create a session with no feedback
    s_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"mode": "standard", "target_temperature_c": 39.0},
    )
    assert s_res.status_code == 201
    s_id = s_res.json()["id"]

    # 3. Fire 4 concurrent identical feedback PATCH requests
    patch_coros = [
        async_client.patch(
            f"/api/v1/therapy/sessions/{s_id}",
            headers=auth_headers,
            json={"feedback": "insufficient_relief"},
        )
        for _ in range(4)
    ]
    responses = await asyncio.gather(*patch_coros)

    # All should return 200 (first applies, remaining are idempotent no-ops)
    for r in responses:
        assert r.status_code == 200
        assert r.json()["feedback"] == "insufficient_relief"

    # Sensitivity index MUST be bumped exactly once: 1.0 -> 1.05 (never 1.10, 1.15, or 1.20)
    prof = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert prof.status_code == 200
    assert prof.json()["sensitivity_index"] == 1.05

    # 4. Test concurrent conflicting feedback on a fresh session
    s_res2 = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"mode": "standard", "target_temperature_c": 38.0},
    )
    assert s_res2.status_code == 201
    s_id2 = s_res2.json()["id"]

    # One request sends insufficient_relief, another sends too_hot concurrently
    conflicting_responses = await asyncio.gather(
        async_client.patch(f"/api/v1/therapy/sessions/{s_id2}", headers=auth_headers, json={"feedback": "insufficient_relief"}),
        async_client.patch(f"/api/v1/therapy/sessions/{s_id2}", headers=auth_headers, json={"feedback": "too_hot"}),
        return_exceptions=True,
    )
    status_codes = [r.status_code for r in conflicting_responses if hasattr(r, "status_code")]
    assert 200 in status_codes
    assert 409 in status_codes


@pytest.mark.asyncio
async def test_therapy_session_date_validation(async_client: AsyncClient, auth_headers: dict):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)

    # 1. POST session with ended_at < started_at -> rejected with 422
    bad_post = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={
            "started_at": (now).isoformat(),
            "ended_at": (now - timedelta(minutes=15)).isoformat(),
            "mode": "standard",
        },
    )
    assert bad_post.status_code == 422

    # 2. Valid session creation
    good_post = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={
            "started_at": now.isoformat(),
            "mode": "standard",
        },
    )
    assert good_post.status_code == 201
    s_id = good_post.json()["id"]

    # 3. PATCH session with ended_at < started_at -> rejected with 400
    bad_patch = await async_client.patch(
        f"/api/v1/therapy/sessions/{s_id}",
        headers=auth_headers,
        json={"ended_at": (now - timedelta(minutes=10)).isoformat()},
    )
    assert bad_patch.status_code == 400
    assert "ended_at cannot be prior to started_at" in bad_patch.json()["detail"]


@pytest.mark.asyncio
async def test_therapy_temperature_bounds(async_client: AsyncClient, auth_headers: dict):
    # 1. Negative temperature rejected (ge=0.0)
    neg_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"mode": "standard", "target_temperature_c": -5.0},
    )
    assert neg_res.status_code == 422

    # 2. Temperature above safety ceiling 44.0 rejected (le=44.0)
    high_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"mode": "standard", "target_temperature_c": 45.0},
    )
    assert high_res.status_code == 422

    # 3. Valid temperature within [0.0, 44.0] accepted
    valid_res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"mode": "standard", "target_temperature_c": 40.5},
    )
    assert valid_res.status_code == 201
    assert valid_res.json()["target_temperature_c"] == 40.5


@pytest.mark.asyncio
async def test_therapy_timestamp_utc_normalization(async_client: AsyncClient, auth_headers: dict):
    # Pass naive datetime string
    naive_started = "2026-08-20T10:00:00"
    naive_ended = "2026-08-20T10:30:00"

    res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={
            "mode": "standard",
            "started_at": naive_started,
            "ended_at": naive_ended,
            "target_temperature_c": 38.0,
        },
    )
    assert res.status_code == 201
    data = res.json()
    assert data["started_at"] is not None
    assert data["ended_at"] is not None
    # Verify response contains UTC timezone offset (+00:00 or Z)
    assert "+00:00" in data["started_at"] or "Z" in data["started_at"]


@pytest.mark.asyncio
async def test_device_duplicate_identifier_cross_user_conflict(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    dev_id = "ESP32-UNIQUE-SN-999"

    # User 1 registers device
    r1 = await async_client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={"device_identifier": dev_id, "name": "User 1 Belt"},
    )
    assert r1.status_code == 201

    # User 2 attempts to register same device -> 409 Conflict
    r2 = await async_client.post(
        "/api/v1/devices",
        headers=other_user_auth_headers,
        json={"device_identifier": dev_id, "name": "User 2 Belt"},
    )
    assert r2.status_code == 409
    assert "already registered to another user" in r2.json()["detail"].lower()

    # User 1 re-registers same device -> updates existing device record (no 500)
    r3 = await async_client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={"device_identifier": dev_id, "name": "User 1 Belt Renamed"},
    )
    assert r3.status_code == 201
    assert r3.json()["name"] == "User 1 Belt Renamed"


@pytest.mark.asyncio
async def test_device_empty_or_whitespace_identifier_rejected(async_client: AsyncClient, auth_headers: dict):
    # Empty string
    r1 = await async_client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={"device_identifier": ""},
    )
    assert r1.status_code == 422

    # Whitespace only
    r2 = await async_client.post(
        "/api/v1/devices",
        headers=auth_headers,
        json={"device_identifier": "   "},
    )
    assert r2.status_code == 422
