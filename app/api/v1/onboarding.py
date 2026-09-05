import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.cycles import check_cycle_overlap
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.cycle import Cycle
from app.models.profile import Profile
from app.schemas.onboarding import OnboardingRequest, OnboardingResponse
from app.schemas.profile import ProfileResponse

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


@router.post(
    "/complete",
    response_model=OnboardingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Complete user onboarding flow (atomic profile and first period setup)",
)
async def complete_onboarding(
    payload: OnboardingRequest,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResponse:
    # 1. Fetch or create profile
    prof_stmt = select(Profile).where(Profile.user_id == current_user_id)
    prof_res = await db.execute(prof_stmt)
    profile = prof_res.scalar_one_or_none()

    if profile is None:
        profile = Profile(
            user_id=current_user_id,
            name=payload.name,
            usual_cycle_days=payload.usual_cycle_days,
            usual_period_days=payload.usual_period_days,
        )
        db.add(profile)
    else:
        if payload.name is not None:
            profile.name = payload.name
        profile.usual_cycle_days = payload.usual_cycle_days
        profile.usual_period_days = payload.usual_period_days

    # 2. Check if cycle starting on this date already exists to preserve idempotency
    cycle_stmt = select(Cycle).where(
        Cycle.user_id == current_user_id,
        Cycle.period_start == payload.last_period_start,
    )
    cycle_res = await db.execute(cycle_stmt)
    existing_cycle = cycle_res.scalar_one_or_none()

    # 3. Check cycle overlap across user's existing periods (excluding identical cycle if re-onboarding)
    await check_cycle_overlap(
        db=db,
        user_id=current_user_id,
        period_start=payload.last_period_start,
        period_end=payload.last_period_end,
        exclude_cycle_id=existing_cycle.id if existing_cycle else None,
    )

    if existing_cycle is None:
        first_cycle = Cycle(
            user_id=current_user_id,
            period_start=payload.last_period_start,
            period_end=payload.last_period_end,
        )
        db.add(first_cycle)
        await db.commit()
        await db.refresh(first_cycle)
        active_cycle = first_cycle
    else:
        # Update end date if provided
        if payload.last_period_end is not None:
            existing_cycle.period_end = payload.last_period_end
        await db.commit()
        await db.refresh(existing_cycle)
        active_cycle = existing_cycle

    await db.refresh(profile)

    return OnboardingResponse(
        message="Onboarding completed successfully.",
        profile=ProfileResponse.model_validate(profile),
        period_id=active_cycle.id,
        period_start=active_cycle.period_start,
        period_end=active_cycle.period_end,
    )
