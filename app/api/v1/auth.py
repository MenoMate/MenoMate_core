import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.profile import Profile
from app.schemas.profile import ProfileResponse, ProfileSyncRequest

router = APIRouter(prefix="/auth", tags=["Auth & Profile"])


@router.post(
    "/sync-profile",
    response_model=ProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or sync profile row for authenticated Supabase user",
)
async def sync_profile(
    payload: ProfileSyncRequest = ProfileSyncRequest(),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    """
    Syncs/initializes the user's profile upon signup or login.
    If the profile already exists, returns the existing record.
    If not, creates a new baseline profile for the Supabase user id.
    """
    stmt = select(Profile).where(Profile.id == current_user_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = Profile(
            id=current_user_id,
            cycle_length_avg=payload.cycle_length_avg or 28,
            period_length_avg=payload.period_length_avg or 5,
            sensitivity_index=payload.sensitivity_index or 1.0,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    
    return profile
