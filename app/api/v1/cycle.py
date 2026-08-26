import uuid
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.cycle import Cycle
from app.models.profile import Profile
from app.schemas.cycle import (
    CurrentCycleStatusResponse,
    CycleEndRequest,
    CycleResponse,
    CycleStartRequest,
)
from app.services.cycle_engine import (
    calculate_cycle_metrics,
    recalculate_user_cycle_average,
)

router = APIRouter(prefix="/cycles", tags=["Cycles"])


async def _get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    stmt = select(Profile).where(Profile.id == user_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = Profile(id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


@router.get(
    "/current",
    response_model=CurrentCycleStatusResponse,
    summary="Get active cycle status, phase indicators, and days until next period",
)
async def get_current_cycle(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentCycleStatusResponse:
    profile = await _get_or_create_profile(db, current_user_id)

    # Find the latest active cycle
    stmt = (
        select(Cycle)
        .where(Cycle.user_id == current_user_id, Cycle.is_active == True)  # noqa: E712
        .order_by(desc(Cycle.start_date))
        .limit(1)
    )
    result = await db.execute(stmt)
    active_cycle = result.scalar_one_or_none()

    if active_cycle is None:
        return CurrentCycleStatusResponse(
            active_cycle=None,
            current_cycle_day=None,
            predicted_ovulation=None,
            predicted_next_period=None,
            days_until_next_period=None,
            cycle_length_avg=profile.cycle_length_avg,
        )

    next_period, ovulation, cycle_day, days_left = calculate_cycle_metrics(
        start_date=active_cycle.start_date,
        cycle_length_avg=profile.cycle_length_avg,
    )

    return CurrentCycleStatusResponse(
        active_cycle=CycleResponse.model_validate(active_cycle),
        current_cycle_day=cycle_day,
        predicted_ovulation=ovulation,
        predicted_next_period=next_period,
        days_until_next_period=days_left,
        cycle_length_avg=profile.cycle_length_avg,
    )


@router.post(
    "/start",
    response_model=CycleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new menstrual cycle",
)
async def start_cycle(
    payload: CycleStartRequest = CycleStartRequest(),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Cycle:
    profile = await _get_or_create_profile(db, current_user_id)
    start_date = payload.start_date or date.today()

    # Close any currently active cycle
    active_stmt = select(Cycle).where(
        Cycle.user_id == current_user_id,
        Cycle.is_active == True,  # noqa: E712
    )
    active_res = await db.execute(active_stmt)
    active_cycles = active_res.scalars().all()
    for cycle in active_cycles:
        cycle.is_active = False
        if cycle.end_date is None:
            # Set previous cycle end date to the day before new start date
            cycle.end_date = start_date

    # Calculate predicted ovulation
    _, predicted_ovulation, _, _ = calculate_cycle_metrics(
        start_date=start_date,
        cycle_length_avg=profile.cycle_length_avg,
    )

    new_cycle = Cycle(
        user_id=current_user_id,
        start_date=start_date,
        end_date=None,
        predicted_ovulation=predicted_ovulation,
        is_active=True,
    )
    db.add(new_cycle)
    await db.commit()
    await db.refresh(new_cycle)

    return new_cycle


@router.put(
    "/{cycle_id}/end",
    response_model=CycleResponse,
    summary="Close cycle and recompute rolling cycle averages",
)
async def end_cycle(
    cycle_id: int,
    payload: CycleEndRequest = CycleEndRequest(),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Cycle:
    stmt = select(Cycle).where(
        Cycle.id == cycle_id,
        Cycle.user_id == current_user_id,
    )
    result = await db.execute(stmt)
    cycle = result.scalar_one_or_none()

    if cycle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cycle not found",
        )

    end_date = payload.end_date or date.today()
    if end_date < cycle.start_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End date cannot be prior to start date",
        )

    cycle.end_date = end_date
    cycle.is_active = False

    await db.commit()
    await db.refresh(cycle)

    # Recalculate rolling 3-cycle average
    await recalculate_user_cycle_average(db, current_user_id, limit=3)
    await db.commit()

    return cycle
