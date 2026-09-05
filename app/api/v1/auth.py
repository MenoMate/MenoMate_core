import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.profile import Profile
from app.schemas.profile import ProfileResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get(
    "/me",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get authenticated user identity and profile",
)
async def get_me(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    """
    Returns the authenticated user's application profile.
    Initializes a baseline profile record if this is the first login.
    """
    stmt = select(Profile).where(Profile.user_id == current_user_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = Profile(user_id=current_user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)

    return profile
