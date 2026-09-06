import asyncio
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.cycles import check_cycle_overlap
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.cycle import Cycle
from app.models.profile import Profile
from app.schemas.onboarding import OnboardingRequest, OnboardingResponse
from app.schemas.profile import ProfileResponse
from app.services.profile import get_or_create_profile

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

_onboarding_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _get_onboarding_lock(user_id: uuid.UUID) -> asyncio.Lock:
    if user_id not in _onboarding_locks:
        _onboarding_locks[user_id] = asyncio.Lock()
    return _onboarding_locks[user_id]


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
    lock = _get_onboarding_lock(current_user_id)
    async with lock:
        try:
            # 1. Fetch or stage profile without committing to ensure atomicity
            profile = await get_or_create_profile(db, current_user_id, commit=False)
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
                active_cycle = first_cycle
            else:
                # Update end date if provided
                if payload.last_period_end is not None:
                    existing_cycle.period_end = payload.last_period_end
                active_cycle = existing_cycle

            # Commit profile and cycle atomically together in one transaction
            await db.commit()
            await db.refresh(profile)
            await db.refresh(active_cycle)

            return OnboardingResponse(
                message="Onboarding completed successfully.",
                profile=ProfileResponse.model_validate(profile),
                period_id=active_cycle.id,
                period_start=active_cycle.period_start,
                period_end=active_cycle.period_end,
            )
        except IntegrityError:
            await db.rollback()
            # Safe recovery if another process committed the profile/cycle
            prof_stmt = select(Profile).where(Profile.user_id == current_user_id)
            res_p = await db.execute(prof_stmt)
            existing_prof = res_p.scalar_one_or_none()
            if existing_prof is not None:
                cyc_stmt = select(Cycle).where(
                    Cycle.user_id == current_user_id,
                    Cycle.period_start == payload.last_period_start,
                )
                res_c = await db.execute(cyc_stmt)
                existing_c = res_c.scalar_one_or_none()
                if existing_c is not None:
                    return OnboardingResponse(
                        message="Onboarding completed successfully.",
                        profile=ProfileResponse.model_validate(existing_prof),
                        period_id=existing_c.id,
                        period_start=existing_c.period_start,
                        period_end=existing_c.period_end,
                    )
            raise
        except Exception:
            await db.rollback()
            raise
