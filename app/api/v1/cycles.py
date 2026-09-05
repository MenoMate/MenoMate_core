import uuid
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.cycle import Cycle
from app.models.profile import Profile
from app.schemas.cycle import (
    CurrentCycleResponse,
    CycleCreate,
    CycleResponse,
    CycleUpdate,
)
from app.services.cycle_calculator import calculate_period_length
from app.services.summary import get_current_cycle_summary

router = APIRouter(prefix="/cycles", tags=["Cycles"])


def _to_cycle_response(cycle: Cycle) -> CycleResponse:
    p_len = calculate_period_length(cycle)
    return CycleResponse(
        id=cycle.id,
        user_id=cycle.user_id,
        period_start=cycle.period_start,
        period_end=cycle.period_end,
        period_length_days=p_len,
        created_at=cycle.created_at,
        updated_at=cycle.updated_at,
    )


async def _check_cycle_overlap(
    db: AsyncSession,
    user_id: uuid.UUID,
    period_start: date,
    period_end: Optional[date],
    exclude_cycle_id: Optional[int] = None,
) -> None:
    stmt = select(Cycle).where(Cycle.user_id == user_id)
    if exclude_cycle_id is not None:
        stmt = stmt.where(Cycle.id != exclude_cycle_id)
    res = await db.execute(stmt)
    existing_cycles = res.scalars().all()

    today = date.today()
    effective_end = period_end or today
    for ec in existing_cycles:
        ec_effective_end = ec.period_end or today
        if period_start == ec.period_start:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A period already exists starting on {period_start}.",
            )
        if max(period_start, ec.period_start) <= min(effective_end, ec_effective_end):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Specified period range ({period_start} to {period_end or 'ongoing'}) overlaps with existing period ({ec.period_start} to {ec.period_end or 'ongoing'}).",
            )


@router.get(
    "/current",
    response_model=CurrentCycleResponse,
    summary="Get active cycle status, current day, bleeding state, and next period prediction",
)
async def get_current_cycle(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentCycleResponse:
    summary = await get_current_cycle_summary(db, current_user_id)
    return CurrentCycleResponse(
        has_data=summary["has_data"],
        current_cycle_day=summary["current_cycle_day"],
        phase=summary["phase"],
        is_bleeding=summary["is_bleeding"],
        latest_period_start=summary.get("latest_period_start"),
        latest_period_end=summary.get("latest_period_end"),
        predicted_cycle_length=summary.get("predicted_cycle_length"),
        predicted_next_period=summary["predicted_next_period"],
        days_until_next_period=summary["days_until_next_period"],
        prediction_confidence=summary["prediction_confidence"],
        prediction_source=summary.get("prediction_source"),
        average_cycle_length=summary["average_cycle_length"],
        average_period_length=summary["average_period_length"],
    )


@router.get(
    "",
    response_model=List[CycleResponse],
    summary="List all logged menstrual periods for user",
)
async def list_cycles(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CycleResponse]:
    stmt = (
        select(Cycle)
        .where(Cycle.user_id == current_user_id)
        .order_by(desc(Cycle.period_start))
    )
    res = await db.execute(stmt)
    cycles = res.scalars().all()
    return [_to_cycle_response(c) for c in cycles]


@router.post(
    "",
    response_model=CycleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a new menstrual period occurrence",
)
async def create_cycle(
    payload: CycleCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CycleResponse:
    # Ensure profile exists
    prof_stmt = select(Profile).where(Profile.user_id == current_user_id)
    prof_res = await db.execute(prof_stmt)
    if not prof_res.scalar_one_or_none():
        db.add(Profile(user_id=current_user_id))
        await db.flush()

    # Overlapping period check
    await _check_cycle_overlap(
        db=db,
        user_id=current_user_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
    )

    cycle = Cycle(
        user_id=current_user_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
    )
    db.add(cycle)
    await db.commit()
    await db.refresh(cycle)
    return _to_cycle_response(cycle)


@router.patch(
    "/{cycle_id}",
    response_model=CycleResponse,
    summary="Update or close an ongoing period occurrence",
)
async def update_cycle(
    cycle_id: int,
    payload: CycleUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CycleResponse:
    stmt = select(Cycle).where(
        Cycle.id == cycle_id,
        Cycle.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    cycle = res.scalar_one_or_none()

    if not cycle:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cycle period not found")

    new_start = payload.period_start if payload.period_start is not None else cycle.period_start
    new_end = payload.period_end if payload.period_end is not None else cycle.period_end

    if new_end and new_end < new_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="period_end cannot be prior to period_start",
        )

    # Check overlap with other periods for this user
    await _check_cycle_overlap(
        db=db,
        user_id=current_user_id,
        period_start=new_start,
        period_end=new_end,
        exclude_cycle_id=cycle_id,
    )

    if payload.period_start is not None:
        cycle.period_start = payload.period_start
    if payload.period_end is not None:
        cycle.period_end = payload.period_end

    await db.commit()
    await db.refresh(cycle)
    return _to_cycle_response(cycle)
