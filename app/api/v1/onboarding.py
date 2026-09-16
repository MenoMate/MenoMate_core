import asyncio
import time
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.cycles import check_cycle_overlap
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.cycle import Cycle
from app.models.profile import Profile
from app.schemas.onboarding import OnboardingRequest, OnboardingResponse
from app.schemas.profile import ProfileResponse
from app.services.profile import get_or_create_profile
from app.services.timezone import user_today, user_today_for, validate_timezone

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])

# Process-local per-user serializer. This is NOT a distributed lock: the
# database unique constraint (uq_cycle_user_period_start) remains the real
# cross-worker guarantee and the IntegrityError path below is its handler.
# Entries are (lock, last_acquired_monotonic); idle entries are evicted
# opportunistically so the map cannot grow without bound.
_onboarding_locks: dict[uuid.UUID, tuple[asyncio.Lock, float]] = {}
_LOCK_IDLE_EVICT_SECONDS = 600.0
_LOCK_EVICT_SCAN_THRESHOLD = 500


def _get_onboarding_lock(user_id: uuid.UUID) -> asyncio.Lock:
    now = time.monotonic()
    entry = _onboarding_locks.get(user_id)
    if entry is not None:
        lock, _ = entry
        _onboarding_locks[user_id] = (lock, now)
        return lock
    if len(_onboarding_locks) >= _LOCK_EVICT_SCAN_THRESHOLD:
        stale = [
            key
            for key, (lock, last_used) in _onboarding_locks.items()
            if (now - last_used) > _LOCK_IDLE_EVICT_SECONDS and not lock.locked()
        ]
        for key in stale:
            del _onboarding_locks[key]
    lock = asyncio.Lock()
    _onboarding_locks[user_id] = (lock, now)
    return lock


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
            # 0. Resolve the authoritative user-local today BEFORE touching
            # the database. The payload timezone (device zone at onboarding
            # time) wins when supplied and valid; otherwise fall back to the
            # stored profile zone, else the documented UTC fallback.
            # DATE fields are user calendar dates — never reinterpreted.
            resolved_tz: Optional[str] = None
            if payload.timezone is not None:
                try:
                    resolved_tz = validate_timezone(payload.timezone)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc))
            if resolved_tz is not None:
                today = user_today(resolved_tz)
            else:
                today = await user_today_for(db, current_user_id)

            # 1. Strict user-local bounds. The coarse schema guard stays as
            # a server-relative backstop; these are the authoritative checks
            # (note: strict `<= today` — onboarding takes no +1 display
            # tolerance, unlike the cycle routes).
            if payload.last_period_start > today:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"last_period_start cannot be in the future (today is {today} in your timezone)",
                )
            if payload.last_period_end is not None and payload.last_period_end > today:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"last_period_end cannot be in the future (today is {today} in your timezone)",
                )

            # 2. Fetch or stage profile without committing to ensure atomicity.
            # Completion is judged on the STORED name (before applying this
            # payload) so a first submission can never trip its own guard.
            profile = await get_or_create_profile(db, current_user_id, commit=False)
            stored_name_set = bool((profile.name or "").strip())

            cyc_all_res = await db.execute(
                select(Cycle).where(Cycle.user_id == current_user_id)
            )
            user_cycles = list(cyc_all_res.scalars().all())
            existing_cycle = next(
                (c for c in user_cycles if c.period_start == payload.last_period_start),
                None,
            )

            # 3. One-time semantics: an already-onboarded account (non-blank
            # stored name AND at least one cycle) may only repeat the exact
            # same start (safe idempotent retry). Anything else is a 409
            # directing the user to the History/cycle-edit path — onboarding
            # must never silently mint a second "first" period.
            if stored_name_set and len(user_cycles) > 0 and existing_cycle is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Onboarding has already been completed for this account. "
                    "To add or correct period dates, use History.",
                )

            # 4. Apply profile fields symmetrically and intentionally.
            # The schema guarantees a stripped non-blank name. Omitted
            # usual_* (None) NEVER erases a stored value — explicit clearing
            # stays a separate edit operation. Timezone only moves forward
            # when the device supplies a valid zone (never cleared to null).
            profile.name = payload.name
            if payload.usual_cycle_days is not None:
                profile.usual_cycle_days = payload.usual_cycle_days
            if payload.usual_period_days is not None:
                profile.usual_period_days = payload.usual_period_days
            if resolved_tz is not None:
                profile.timezone = resolved_tz

            # 5. Overlap across existing periods (excluding the identical
            # cycle on idempotent repeat), bounded by user-local today.
            await check_cycle_overlap(
                db=db,
                user_id=current_user_id,
                period_start=payload.last_period_start,
                period_end=payload.last_period_end,
                exclude_cycle_id=existing_cycle.id if existing_cycle else None,
                today=today,
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
                # Idempotent repeat mirrors the request's stated period
                # state: an explicit null end (user switched to Ongoing)
                # reopens the period instead of preserving a stale end.
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
