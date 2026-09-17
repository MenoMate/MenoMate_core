"""Production-hardening regression tests: health, auth isolation (IDOR),
input validation, and safe production configuration behavior.

Focused on meaningful behavior only; not a coverage exercise.
"""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient

import app.core.security as security_module


@pytest.mark.asyncio
async def test_health_is_public(async_client: AsyncClient):
    res = await async_client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert "service" in body


@pytest.mark.asyncio
async def test_root_is_public(async_client: AsyncClient):
    res = await async_client.get("/")
    assert res.status_code == 200
    assert res.json()["health"] == "/health"


@pytest.mark.asyncio
async def test_protected_routes_still_require_auth(async_client: AsyncClient):
    for path in (
        "/api/v1/cycles",
        "/api/v1/logs",
        "/api/v1/summary/current",
        "/api/v1/devices",
        "/api/v1/therapy/sessions",
    ):
        res = await async_client.get(path)
        assert res.status_code == 401, f"{path} must require authentication"


@pytest.mark.asyncio
async def test_cross_user_log_patch_is_not_found(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    target = str(date.today() - timedelta(days=6))
    created = await async_client.post(
        "/api/v1/logs", headers=auth_headers, json={"log_date": target, "pain": 5}
    )
    assert created.status_code == 200
    log_id = created.json()["id"]

    # Another authenticated user must not be able to read or mutate it by ID.
    cross_patch = await async_client.patch(
        f"/api/v1/logs/{log_id}", headers=other_user_auth_headers, json={"pain": 1}
    )
    assert cross_patch.status_code == 404

    # Owner can still update it.
    own_patch = await async_client.patch(
        f"/api/v1/logs/{log_id}", headers=auth_headers, json={"pain": 2}
    )
    assert own_patch.status_code == 200
    assert own_patch.json()["pain"] == 2


@pytest.mark.asyncio
async def test_cross_user_cycle_patch_is_not_found(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    start = str(date.today() - timedelta(days=30))
    end = str(date.today() - timedelta(days=26))
    created = await async_client.post(
        "/api/v1/cycles",
        headers=auth_headers,
        json={"period_start": start, "period_end": end},
    )
    assert created.status_code == 201
    cycle_id = created.json()["id"]

    cross = await async_client.patch(
        f"/api/v1/cycles/{cycle_id}",
        headers=other_user_auth_headers,
        json={"period_end": end},
    )
    assert cross.status_code == 404


@pytest.mark.asyncio
async def test_invalid_timezone_rejected(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.patch(
        "/api/v1/profile", headers=auth_headers, json={"timezone": "Not/AZone"}
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_oversize_care_message_rejected(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "x" * 501},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_invalid_device_uuid_returns_422_not_500(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.delete(
        "/api/v1/devices/not-a-uuid", headers=auth_headers
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_jwks_failure_returns_generic_401(
    async_client: AsyncClient, monkeypatch
):
    """JWKS/network internals must not leak through auth error responses."""
    from datetime import datetime, timezone as dt_timezone

    import jwt

    from app.core.config import settings

    class _FailingJWKSClient:
        def get_signing_key_from_jwt(self, token):
            raise ConnectionError("kms.internal.svc.cluster.local:8443 timed out")

    monkeypatch.setattr(
        security_module, "get_jwks_client", lambda: _FailingJWKSClient()
    )

    # Build a well-formed ES256 token; key retrieval is forced to fail.
    from cryptography.hazmat.primitives.asymmetric import ec

    ec_key = ec.generate_private_key(ec.SECP256R1())
    future_exp = int(
        (datetime.now(dt_timezone.utc) + timedelta(hours=1)).timestamp()
    )
    payload = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    token = jwt.encode(payload, ec_key, algorithm="ES256", headers={"kid": "x"})

    res = await async_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Could not validate credentials"
    assert "internal" not in res.json()["detail"].lower()
    assert "timed out" not in res.json()["detail"].lower()


def test_wildcard_cors_disables_credentials():
    """Regression: allow_origins=['*'] must never pair with credentials."""
    from fastapi.testclient import TestClient

    from app.core.config import settings

    original = settings.ALLOWED_ORIGINS
    settings.ALLOWED_ORIGINS = ["*"]
    try:
        from app.main import create_app

        test_app = create_app()
        cors = next(
            m
            for m in test_app.user_middleware
            if m.cls.__name__ == "CORSMiddleware"
        )
        assert cors.kwargs["allow_credentials"] is False
    finally:
        settings.ALLOWED_ORIGINS = original


def test_production_env_placeholders_rejected():
    import pydantic

    from app.core.config import Settings

    with pytest.raises(pydantic.ValidationError):
        Settings(SUPABASE_URL="https://your-project-ref.supabase.co")
