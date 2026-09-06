import uuid
from typing import Optional, Set
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

security_scheme = HTTPBearer(auto_error=True)

SUPPORTED_ALGORITHMS: Set[str] = {"HS256", "RS256", "ES256"}

_jwks_client: Optional[jwt.PyJWKClient] = None


def get_jwks_client() -> jwt.PyJWKClient:
    """
    Returns a cached PyJWKClient instance targeting the configured JWKS endpoint.
    Caches signing keys to avoid redundant network round-trips per request.
    """
    global _jwks_client
    url = settings.jwks_url
    if _jwks_client is None or getattr(_jwks_client, "_target_url", None) != url:
        client = jwt.PyJWKClient(url, cache_keys=True, max_cached_keys=16)
        client._target_url = url
        _jwks_client = client
    return _jwks_client


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> uuid.UUID:
    """
    Extracts and validates Supabase JWT claims from Authorization header.
    Strictly enforces:
    - Explicit algorithm validation (rejects unsupported, missing, or 'none' algorithms)
    - Cryptographic signature check (symmetric HS256 with secret or asymmetric RS256/ES256 via JWKS)
    - Expiration (exp)
    - Mandatory audience claim (aud must be exactly 'authenticated')
    - Mandatory issuer claim (iss must be exactly '{SUPABASE_URL}/auth/v1')
    - Mandatory subject claim (sub as a valid UUID)
    Every protected database operation must scope queries by this returned user_id.
    """
    token = credentials.credentials

    try:
        # Inspect unverified header to determine signing algorithm
        unverified_header = jwt.get_unverified_header(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    alg = unverified_header.get("alg")
    if not alg or alg == "none" or alg not in SUPPORTED_ALGORITHMS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported or missing token signing algorithm: {alg}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        if alg in ("RS256", "ES256"):
            # Asymmetric signing via Supabase JWKS public key
            try:
                jwks_client = get_jwks_client()
                signing_key = jwks_client.get_signing_key_from_jwt(token).key
            except Exception as e:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Failed to retrieve verification key: {str(e)}",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[alg],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": False,
                    "verify_iss": False,
                    "require": ["exp", "aud", "iss", "sub"],
                },
            )
        elif alg == "HS256":
            # Symmetric signing via project SUPABASE_JWT_SECRET
            secret = (settings.SUPABASE_JWT_SECRET or "").strip()
            if not secret:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="HS256 authentication secret is not configured",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            payload = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": False,
                    "verify_iss": False,
                    "require": ["exp", "aud", "iss", "sub"],
                },
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported token algorithm: {alg}",
                headers={"WWW-Authenticate": "Bearer"},
            )

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.MissingRequiredClaimError as e:
        claim_name = getattr(e, "claim", str(e))
        if claim_name == "exp":
            detail = "Token missing expiration claim"
        elif claim_name == "sub":
            detail = "Token missing subject claim"
        elif claim_name == "aud":
            detail = "Token missing audience claim"
        elif claim_name == "iss":
            detail = "Token missing issuer claim"
        else:
            detail = f"Token missing {claim_name} claim"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token signature",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.DecodeError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except HTTPException:
        raise
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 1. Require and validate audience claim (must be exactly 'authenticated')
    aud = payload.get("aud")
    if not aud:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing audience claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if aud != "authenticated":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Require and validate issuer claim (must be exactly '{SUPABASE_URL}/auth/v1')
    iss = payload.get("iss")
    if not iss:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing issuer claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expected_iss = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"
    if iss != expected_iss:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Require and validate subject UUID claim
    user_id_str: Optional[str] = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return uuid.UUID(str(user_id_str))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token subject UUID",
            headers={"WWW-Authenticate": "Bearer"},
        )

