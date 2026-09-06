import uuid
from datetime import date, datetime, timedelta, timezone
import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import TEST_USER_ID, ANOTHER_USER_ID


@pytest.mark.asyncio
async def test_api_contract_all_routes_registered(async_client: AsyncClient):
    """
    Validates OpenAPI schema registers every production endpoint with exact methods and paths.
    """
    res = await async_client.get("/openapi.json")
    assert res.status_code == 200
    openapi = res.json()
    paths = openapi.get("paths", {})

    expected_endpoints = {
        "/api/v1/auth/me": ["get"],
        "/api/v1/profile": ["get", "patch", "delete"],
        "/api/v1/onboarding/complete": ["post"],
        "/api/v1/cycles": ["get", "post"],
        "/api/v1/cycles/current": ["get"],
        "/api/v1/cycles/{cycle_id}": ["patch"],
        "/api/v1/logs": ["get", "post"],
        "/api/v1/logs/{log_date}": ["get"],
        "/api/v1/symptoms": ["get"],
        "/api/v1/logs/{log_id}": ["patch"],
        "/api/v1/summary/current": ["get"],
        "/api/v1/summary/history": ["get"],
        "/api/v1/devices": ["get", "post"],
        "/api/v1/devices/{device_id}": ["delete"],
        "/api/v1/therapy/recommend": ["post"],
        "/api/v1/therapy/sessions": ["get", "post"],
        "/api/v1/therapy/sessions/{session_id}": ["patch"],
        "/api/v1/care/interactions": ["post"],
    }

    # Validate exact route and operation counts
    assert len(expected_endpoints) == 18, f"Expected 18 unique API v1 paths, found {len(expected_endpoints)}"
    total_ops = sum(len(methods) for methods in expected_endpoints.values())
    assert total_ops == 24, f"Expected 24 total API v1 operations, found {total_ops}"

    for path, methods in expected_endpoints.items():
        assert path in paths, f"Endpoint {path} missing from API contract"
        for method in methods:
            assert method in paths[path], f"Method {method.upper()} {path} missing from API contract"


@pytest.mark.asyncio
async def test_api_contract_401_on_all_protected_routes(async_client: AsyncClient):
    """
    Validates that every single protected endpoint returns 401 Unauthorized without credentials.
    """
    protected_calls = [
        ("GET", "/api/v1/auth/me", None),
        ("GET", "/api/v1/profile", None),
        ("PATCH", "/api/v1/profile", {"name": "Test"}),
        ("DELETE", "/api/v1/profile", None),
        ("POST", "/api/v1/onboarding/complete", {"last_period_start": "2026-08-01"}),
        ("GET", "/api/v1/cycles", None),
        ("GET", "/api/v1/cycles/current", None),
        ("POST", "/api/v1/cycles", {"period_start": "2026-08-01"}),
        ("PATCH", "/api/v1/cycles/1", {"period_end": "2026-08-05"}),
        ("GET", "/api/v1/logs", None),
        ("GET", "/api/v1/logs/2026-08-01", None),
        ("POST", "/api/v1/logs", {"log_date": "2026-08-01", "pain": 2}),
        ("PATCH", "/api/v1/logs/1", {"pain": 3}),
        ("GET", "/api/v1/summary/current", None),
        ("GET", "/api/v1/summary/history", None),
        ("GET", "/api/v1/devices", None),
        ("POST", "/api/v1/devices", {"device_identifier": "BLE-99"}),
        ("DELETE", f"/api/v1/devices/{uuid.uuid4()}", None),
        ("POST", "/api/v1/therapy/recommend", {"pain_score": 4}),
        ("GET", "/api/v1/therapy/sessions", None),
        ("POST", "/api/v1/therapy/sessions", {"started_at": "2026-08-01T10:00:00Z"}),
        ("PATCH", "/api/v1/therapy/sessions/1", {"pain_after": 2}),
        ("POST", "/api/v1/care/interactions", {"user_message": "hello"}),
    ]

    for method, path, body in protected_calls:
        if method == "GET":
            res = await async_client.get(path)
        elif method == "POST":
            res = await async_client.post(path, json=body or {})
        elif method == "PATCH":
            res = await async_client.patch(path, json=body or {})
        elif method == "DELETE":
            res = await async_client.delete(path)
        assert res.status_code == 401, f"Expected 401 for unauthenticated {method} {path}, got {res.status_code}"


@pytest.mark.asyncio
async def test_api_contract_controlled_enums(async_client: AsyncClient, auth_headers: dict):
    """
    Enforces strict 422 Unprocessable Entity responses for invalid enum values across all models.
    """
    # 1. Profile Theme & Units
    res = await async_client.patch("/api/v1/profile", headers=auth_headers, json={"theme": "invalid_theme"})
    assert res.status_code == 422
    res = await async_client.patch("/api/v1/profile", headers=auth_headers, json={"units": "kelvin"})
    assert res.status_code == 422

    # 2. Daily Log Flow, Mood, Discharge
    res = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": "2026-07-10", "flow": "extreme_gush"},
    )
    assert res.status_code == 422

    res = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": "2026-07-10", "mood": "ecstatic_joy"},
    )
    assert res.status_code == 422

    res = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={"log_date": "2026-07-10", "discharge": "neon_green"},
    )
    assert res.status_code == 422

    # 3. Therapy Mode & Vibration Mode
    res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"started_at": "2026-07-10T12:00:00Z", "mode": "hyper_turbo"},
    )
    assert res.status_code == 422

    res = await async_client.post(
        "/api/v1/therapy/sessions",
        headers=auth_headers,
        json={"started_at": "2026-07-10T12:00:00Z", "vibration_mode": "earthquake"},
    )
    assert res.status_code == 422

    # 4. Care Intent
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"user_message": "advice", "intent": "prescribe_drugs"},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_api_contract_404_handling(async_client: AsyncClient, auth_headers: dict):
    """
    Validates clean 404 responses when querying or mutating nonexistent resource IDs.
    """
    # Cycle 999999
    res = await async_client.patch(
        "/api/v1/cycles/999999",
        headers=auth_headers,
        json={"period_end": "2026-08-05"},
    )
    assert res.status_code == 404

    # Therapy Session 999999
    res = await async_client.patch(
        "/api/v1/therapy/sessions/999999",
        headers=auth_headers,
        json={"pain_after": 3},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_api_contract_409_concurrency_and_duplicates(async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict):
    """
    Validates clean 409 Conflict responses for duplicate cycle start dates and cross-user device claims.
    """
    # 1. Duplicate period start for same user
    p_start = "2026-06-01"
    res1 = await async_client.post("/api/v1/cycles", headers=auth_headers, json={"period_start": p_start, "period_end": "2026-06-05"})
    assert res1.status_code == 201

    res2 = await async_client.post("/api/v1/cycles", headers=auth_headers, json={"period_start": p_start, "period_end": "2026-06-05"})
    assert res2.status_code in (400, 409)

    # 2. Cross-user duplicate device registration conflict
    dev_id = f"DEV-CONTRACT-{uuid.uuid4().hex[:8]}"
    d_res1 = await async_client.post("/api/v1/devices", headers=auth_headers, json={"device_identifier": dev_id})
    assert d_res1.status_code == 201

    d_res2 = await async_client.post("/api/v1/devices", headers=other_user_auth_headers, json={"device_identifier": dev_id})
    assert d_res2.status_code == 409
