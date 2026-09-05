import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.profile import Profile
from app.schemas.profile import ProfileResponse, ProfileUpdate
from app.services.profile import get_or_create_profile

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get(
    "",
    response_model=ProfileResponse,
    summary="Get user profile",
)
async def get_profile(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    return await get_or_create_profile(db, current_user_id)


@router.patch(
    "",
    response_model=ProfileResponse,
    summary="Update user profile preferences and usual cycle lengths",
    description="Updates user profile preferences. Explicitly passing null for usual_cycle_days, usual_period_days, or name clears those fields ('I am not sure' state).",
)
async def update_profile(
    payload: ProfileUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    profile = await get_or_create_profile(db, current_user_id)
    fields_set = payload.model_fields_set

    if "name" in fields_set:
        profile.name = payload.name
    if "usual_cycle_days" in fields_set:
        profile.usual_cycle_days = payload.usual_cycle_days
    if "usual_period_days" in fields_set:
        profile.usual_period_days = payload.usual_period_days
    if "theme" in fields_set and payload.theme is not None:
        profile.theme = payload.theme.value
    if "units" in fields_set and payload.units is not None:
        profile.units = payload.units.value

    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete user application profile and all associated data",
    description=(
        "Deletes the user profile record from PostgreSQL, cascading deletion across all associated "
        "application records (cycles, daily logs, therapy sessions, devices). "
        "Note: This removes PostgreSQL application data only; complete Supabase Auth user deletion "
        "requires Supabase Admin/Service-Role API invocation."
    ),
)
async def delete_profile(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Profile).where(Profile.user_id == current_user_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile:
        await db.delete(profile)
        await db.commit()
    return None
