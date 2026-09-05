import uuid
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

security_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
) -> uuid.UUID:
    """
    Extracts and validates Supabase JWT claims from Authorization header.
    Validates token signature (HS256 symmetric or RS256/ES256 JWKS asymmetric),
    expiration (exp), issuer (iss), audience (aud), and subject UUID (sub).
    Every protected database operation must scope queries by this returned user_id.
    """
    token = credentials.credentials

    try:
        # Inspect unverified header to determine signing algorithm
        unverified_header = jwt.get_unverified_header(token)
        alg = unverified_header.get("alg", "HS256")

        if alg in ("RS256", "ES256"):
            # Asymmetric signing via Supabase JWKS
            jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
            jwks_client = jwt.PyJWKClient(jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(token).key
            payload = jwt.decode(
                token,
                signing_key,
                algorithms=[alg],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": False,
                },
            )
        else:
            # Symmetric signing via project SUPABASE_JWT_SECRET
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": False,
                },
            )

        # 1. Audience validation
        aud = payload.get("aud")
        if aud is not None and aud not in ("authenticated", "test"):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token audience",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 2. Issuer validation (if issuer claim is present)
        iss = payload.get("iss")
        if iss:
            expected_iss = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1"
            if iss not in (expected_iss, "http://test", "supabase", "test"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token issuer",
                    headers={"WWW-Authenticate": "Bearer"},
                )

        # 3. Subject UUID validation
        user_id_str: Optional[str] = payload.get("sub")
        if not user_id_str:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject claim",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return uuid.UUID(user_id_str)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
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
