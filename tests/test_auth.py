from datetime import datetime, timedelta, timezone
import jwt
import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import ANOTHER_USER_ID, TEST_USER_ID


@pytest.mark.asyncio
async def test_auth_missing_token(async_client: AsyncClient):
    res = await async_client.get("/api/v1/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_auth_invalid_token(async_client: AsyncClient):
    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )
    assert res.status_code == 401
    assert "Could not validate credentials" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_malformed_token(async_client: AsyncClient):
    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.payload.structure"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_auth_expired_token(async_client: AsyncClient):
    # Expired token in the past
    past_exp = datetime.now(timezone.utc) - timedelta(minutes=10)
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": int(past_exp.timestamp()),
    }
    expired_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == 401
    assert "Token has expired" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_missing_exp(async_client: AsyncClient):
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
    }
    no_exp_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {no_exp_token}"},
    )
    assert res.status_code == 401
    assert "Token missing expiration claim" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_invalid_audience(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "unauthorized_audience",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    bad_aud_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bad_aud_token}"},
    )
    assert res.status_code == 401
    assert "Invalid token audience" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_invalid_issuer(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": "https://malicious-issuer.com/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    bad_iss_token = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")

    res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {bad_iss_token}"},
    )
    assert res.status_code == 401
    assert "Invalid token issuer" in res.json()["detail"]


@pytest.mark.asyncio
async def test_auth_rejects_test_audience_and_test_issuer(async_client: AsyncClient):
    expected_iss = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())

    # 1. aud="test" must be rejected in production authentication
    payload_bad_aud = {
        "sub": str(TEST_USER_ID),
        "aud": "test",
        "iss": expected_iss,
        "role": "authenticated",
        "exp": future_exp,
    }
    token_bad_aud = jwt.encode(payload_bad_aud, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res_aud = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_bad_aud}"},
    )
    assert res_aud.status_code == 401
    assert "Invalid token audience" in res_aud.json()["detail"]

    # 2. iss="test" must be rejected in production authentication
    payload_bad_iss = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": "test",
        "role": "authenticated",
        "exp": future_exp,
    }
    token_bad_iss = jwt.encode(payload_bad_iss, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res_iss = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_bad_iss}"},
    )
    assert res_iss.status_code == 401
    assert "Invalid token issuer" in res_iss.json()["detail"]


@pytest.mark.asyncio
async def test_auth_valid_token_me(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "user_id" in data
    assert data["user_id"] == str(TEST_USER_ID)
    assert data["theme"] == "system"
    assert data["units"] == "metric"


@pytest.mark.asyncio
async def test_profile_update_and_delete(async_client: AsyncClient, auth_headers: dict):
    # Update profile
    patch_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"name": "Aria", "theme": "dark", "usual_cycle_days": 30},
    )
    assert patch_res.status_code == 200
    p_data = patch_res.json()
    assert p_data["name"] == "Aria"
    assert p_data["theme"] == "dark"
    assert p_data["usual_cycle_days"] == 30

    # Get profile
    get_res = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Aria"

    # Delete profile
    del_res = await async_client.delete("/api/v1/profile", headers=auth_headers)
    assert del_res.status_code == 204


@pytest.mark.asyncio
async def test_cross_user_profile_isolation(
    async_client: AsyncClient, auth_headers: dict, other_user_auth_headers: dict
):
    # User 1 sets their name
    await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"name": "User One"},
    )

    # User 2 sets their name
    await async_client.patch(
        "/api/v1/profile",
        headers=other_user_auth_headers,
        json={"name": "User Two"},
    )

    # User 1 gets their profile
    res1 = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res1.json()["name"] == "User One"
    assert res1.json()["user_id"] == str(TEST_USER_ID)

    # User 2 gets their profile
    res2 = await async_client.get("/api/v1/profile", headers=other_user_auth_headers)
    assert res2.json()["name"] == "User Two"
    assert res2.json()["user_id"] == str(ANOTHER_USER_ID)


@pytest.mark.asyncio
async def test_profile_patch_null_semantics(async_client: AsyncClient, auth_headers: dict):
    # 1. Populate baseline values
    init_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"name": "Aria", "usual_cycle_days": 28, "usual_period_days": 5},
    )
    assert init_res.status_code == 200
    assert init_res.json()["name"] == "Aria"
    assert init_res.json()["usual_cycle_days"] == 28
    assert init_res.json()["usual_period_days"] == 5

    # 2. Explicitly clear nullable values to None ("I'm not sure" state)
    clear_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"name": None, "usual_cycle_days": None, "usual_period_days": None},
    )
    assert clear_res.status_code == 200
    cleared = clear_res.json()
    assert cleared["name"] is None
    assert cleared["usual_cycle_days"] is None
    assert cleared["usual_period_days"] is None

    # 3. Verify omitted fields remain unchanged (None) when updating theme
    update_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"theme": "dark"},
    )
    assert update_res.status_code == 200
    data = update_res.json()
    assert data["theme"] == "dark"
    assert data["name"] is None
    assert data["usual_cycle_days"] is None
    assert data["usual_period_days"] is None


def test_settings_rejects_insecure_placeholders():
    from app.core.config import Settings
    import pydantic

    # 1. Missing or placeholder SUPABASE_URL
    with pytest.raises(pydantic.ValidationError) as exc1:
        Settings(
            SUPABASE_URL="https://your-project-ref.supabase.co",
            SUPABASE_JWT_SECRET="strong-secret-key-32-chars-long!",
        )
    assert "insecure configuration" in str(exc1.value).lower()

    # 2. Missing or placeholder SUPABASE_JWT_SECRET
    with pytest.raises(pydantic.ValidationError) as exc2:
        Settings(
            SUPABASE_URL="https://valid-project.supabase.co",
            SUPABASE_JWT_SECRET="your-supabase-jwt-secret",
        )
    assert "insecure configuration" in str(exc2.value).lower()

    # 3. Valid non-placeholder settings succeed
    valid_cfg = Settings(
        SUPABASE_URL="https://valid-project.supabase.co",
        SUPABASE_JWT_SECRET="strong-secret-key-32-chars-long!",
    )
    assert valid_cfg.SUPABASE_URL == "https://valid-project.supabase.co"


@pytest.mark.asyncio
async def test_profile_sensitivity_not_client_writable(async_client: AsyncClient, auth_headers: dict):
    # Fetch current baseline sensitivity
    res_before = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res_before.status_code == 200
    baseline_sens = res_before.json()["sensitivity_index"]

    # Attempt to directly patch sensitivity_index to a new value
    patch_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"sensitivity_index": 1.45},
    )
    assert patch_res.status_code == 200

    # Sensitivity index MUST remain untouched by direct client writes
    res_after = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert res_after.json()["sensitivity_index"] == baseline_sens


@pytest.mark.asyncio
async def test_profile_controlled_enums_theme_and_units(async_client: AsyncClient, auth_headers: dict):
    # Valid enum values
    valid_res = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"theme": "light", "units": "imperial"},
    )
    assert valid_res.status_code == 200
    data = valid_res.json()
    assert data["theme"] == "light"
    assert data["units"] == "imperial"

    # Invalid theme value -> 422
    bad_theme = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"theme": "neon_rainbow"},
    )
    assert bad_theme.status_code == 422

    # Invalid units value -> 422
    bad_units = await async_client.patch(
        "/api/v1/profile",
        headers=auth_headers,
        json={"units": "kelvin"},
    )
    assert bad_units.status_code == 422


# ==============================================================================
# Comprehensive JWT Requirements Test Suite (A through T)
# ==============================================================================
from cryptography.hazmat.primitives.asymmetric import rsa, ec
from cryptography.hazmat.primitives import serialization
from unittest.mock import MagicMock
import app.core.security as security_module


class _MockJWK:
    def __init__(self, key):
        self.key = key


class _MockJWKSClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        return _MockJWK(self._key)


@pytest.mark.asyncio
async def test_jwt_a_valid_hs256_token(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.get("/api/v1/auth/me", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["user_id"] == str(TEST_USER_ID)


@pytest.mark.asyncio
async def test_jwt_b_valid_rs256_token(async_client: AsyncClient, monkeypatch):
    # Generate ephemeral RSA keypair
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_pub = rsa_key.public_key()
    monkeypatch.setattr(security_module, "get_jwks_client", lambda: _MockJWKSClient(rsa_pub))

    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    rs_token = jwt.encode(payload, rsa_key, algorithm="RS256", headers={"kid": "test-rsa-kid"})

    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {rs_token}"})
    assert res.status_code == 200
    assert res.json()["user_id"] == str(TEST_USER_ID)


@pytest.mark.asyncio
async def test_jwt_c_valid_es256_token(async_client: AsyncClient, monkeypatch):
    # Generate ephemeral EC P-256 keypair (matches live Supabase algorithm)
    ec_key = ec.generate_private_key(ec.SECP256R1())
    ec_pub = ec_key.public_key()
    monkeypatch.setattr(security_module, "get_jwks_client", lambda: _MockJWKSClient(ec_pub))

    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    es_token = jwt.encode(payload, ec_key, algorithm="ES256", headers={"kid": "7650ece3-a91e-495a-804a-adee2977089c"})

    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {es_token}"})
    assert res.status_code == 200
    assert res.json()["user_id"] == str(TEST_USER_ID)


@pytest.mark.asyncio
async def test_jwt_d_expired_token(async_client: AsyncClient):
    past_exp = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": past_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Token has expired" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_e_missing_exp(async_client: AsyncClient):
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Token missing expiration claim" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_f_invalid_signature(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, "wrong-signature-secret-key-12345678", algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Invalid token signature" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_g_missing_issuer(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Token missing issuer claim" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_h_wrong_issuer(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": "https://attacker.com/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Invalid token issuer" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_i_missing_audience(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Token missing audience claim" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_j_wrong_audience(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "wrong_audience_role",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Invalid token audience" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_k_missing_subject(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Token missing subject claim" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_l_invalid_uuid_subject(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": "not-a-valid-uuid",
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Invalid token subject UUID" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_m_unsupported_algorithm(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    # 64-byte key for HS384
    tok = jwt.encode(payload, "strong-secret-key-64-bytes-long-padding-for-sha384-security-test!!", algorithm="HS384")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Unsupported or missing token signing algorithm" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_n_malformed_token(async_client: AsyncClient):
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": "Bearer this.is.not.a.valid.jwt"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_jwt_o_unsigned_token(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    # Unsigned token (alg=none)
    tok = jwt.encode(payload, key="", algorithm=None)
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Unsupported or missing token signing algorithm" in res.json()["detail"]


@pytest.mark.asyncio
async def test_jwt_p_altered_payload_or_signature(async_client: AsyncClient, auth_headers: dict):
    valid_token = auth_headers["Authorization"].split(" ")[1]
    parts = valid_token.split(".")
    # Tamper with the payload part
    altered_token = f"{parts[0]}.eyJhZG1pbiI6dHJ1ZX0.{parts[2]}"
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {altered_token}"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_jwt_q_legacy_test_issuer_rejected(async_client: AsyncClient):
    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": "test",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "Invalid token issuer" in res.json()["detail"]


def test_jwt_r_placeholder_configuration_rejected():
    from app.core.config import Settings
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        Settings(SUPABASE_URL="https://your-project-ref.supabase.co")

    with pytest.raises(pydantic.ValidationError):
        Settings(
            SUPABASE_URL="https://valid-project.supabase.co",
            SUPABASE_JWT_SECRET="your-supabase-jwt-secret-here",
        )


@pytest.mark.asyncio
async def test_jwt_s_asymmetric_without_secret_works(async_client: AsyncClient, monkeypatch):
    ec_key = ec.generate_private_key(ec.SECP256R1())
    ec_pub = ec_key.public_key()
    monkeypatch.setattr(security_module, "get_jwks_client", lambda: _MockJWKSClient(ec_pub))
    # Clear SUPABASE_JWT_SECRET to prove asymmetric doesn't need it
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", None)

    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, ec_key, algorithm="ES256", headers={"kid": "test-kid"})
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 200
    assert res.json()["user_id"] == str(TEST_USER_ID)


@pytest.mark.asyncio
async def test_jwt_t_hs256_without_secret_fails_cleanly(async_client: AsyncClient, monkeypatch):
    # When SUPABASE_JWT_SECRET is None or empty, receiving an HS256 token must return 401
    monkeypatch.setattr(settings, "SUPABASE_JWT_SECRET", None)

    future_exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    payload = {
        "sub": str(TEST_USER_ID),
        "aud": "authenticated",
        "iss": f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1",
        "role": "authenticated",
        "exp": future_exp,
    }
    tok = jwt.encode(payload, "secret-key-32-chars-long-padding!!", algorithm="HS256")
    res = await async_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert res.status_code == 401
    assert "HS256 authentication secret is not configured" in res.json()["detail"]

