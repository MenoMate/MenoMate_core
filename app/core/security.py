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
    Extracts and validates Supabase JWT token from Authorization header.
    Returns the authenticated user's UUID.
    """
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode Supabase JWT signed with HMAC-SHA256
        # Supabase typically uses audience="authenticated"
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
        user_id_str: Optional[str] = payload.get("sub")
        if not user_id_str:
            raise credentials_exception
        
        return uuid.UUID(user_id_str)
    except jwt.PyJWTError:
        raise credentials_exception
    except ValueError:
        # If user_id_str is not a valid UUID
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID format in token",
            headers={"WWW-Authenticate": "Bearer"},
        )
