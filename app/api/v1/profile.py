import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.profile import Profile
from app.schemas.profile import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["Profile"])


async def _get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    stmt = select(Profile).where(Profile.user_id == user_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


@router.get(
    "",
    response_model=ProfileResponse,
    summary="Get user profile",
)
async def get_profile(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    return await _get_or_create_profile(db, current_user_id)


@router.patch(
    "",
    response_model=ProfileResponse,
    summary="Update user profile preferences and usual cycle lengths",
)
async def update_profile(
    payload: ProfileUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Profile:
    profile = await _get_or_create_profile(db, current_user_id)

    if payload.name is not None:
        profile.name = payload.name
    if payload.usual_cycle_days is not None:
        profile.usual_cycle_days = payload.usual_cycle_days
    if payload.usual_period_days is not None:
        profile.usual_period_days = payload.usual_period_days
    if payload.theme is not None:
        profile.theme = payload.theme
    if payload.units is not None:
        profile.units = payload.units
    if payload.sensitivity_index is not None:
        profile.sensitivity_index = payload.sensitivity_index

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
