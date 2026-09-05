import uuid
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.daily_log import DailyLog
from app.models.profile import Profile
from app.models.symptom_log import SymptomLog
from app.schemas.daily_log import (
    SUPPORTED_SYMPTOMS,
    DailyLogCreate,
    DailyLogResponse,
    DailyLogUpdate,
    SymptomItem,
    SymptomMeta,
)

router = APIRouter(tags=["Daily Logs & Symptoms"])


async def _ensure_profile_exists(db: AsyncSession, user_id: uuid.UUID) -> None:
    stmt = select(Profile).where(Profile.user_id == user_id)
    res = await db.execute(stmt)
    if not res.scalar_one_or_none():
        db.add(Profile(user_id=user_id))
        await db.flush()


@router.get(
    "/symptoms",
    response_model=List[SymptomMeta],
    summary="Get supported semantic symptom identifiers and metadata",
)
async def get_supported_symptoms() -> List[SymptomMeta]:
    """
    Returns static supported symptom definitions without requiring a database query.
    """
    return [SymptomMeta(**s) for s in SUPPORTED_SYMPTOMS]


@router.get(
    "/logs/{log_date}",
    response_model=Optional[DailyLogResponse],
    summary="Get daily log and child symptoms for a specific calendar date",
)
async def get_log_by_date(
    log_date: date,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[DailyLog]:
    stmt = (
        select(DailyLog)
        .where(DailyLog.user_id == current_user_id, DailyLog.log_date == log_date)
        .options(selectinload(DailyLog.symptoms))
    )
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


@router.get(
    "/logs",
    response_model=List[DailyLogResponse],
    summary="Query daily logs within an optional date range",
)
async def query_logs(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[DailyLog]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail="start_date cannot be after end_date",
        )

    stmt = select(DailyLog).where(DailyLog.user_id == current_user_id)
    if start_date:
        stmt = stmt.where(DailyLog.log_date >= start_date)
    if end_date:
        stmt = stmt.where(DailyLog.log_date <= end_date)
    stmt = stmt.order_by(desc(DailyLog.log_date)).options(selectinload(DailyLog.symptoms))
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post(
    "/logs",
    response_model=DailyLogResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or replace complete daily log (full day upsert)",
    description=(
        "Full replacement/upsert for the specified calendar date. Replaces pain score, mood, discharge, "
        "flow, notes, and child symptoms completely. For partial field updates without overwriting unmentioned "
        "fields, use PATCH /logs/{log_id} instead."
    ),
)
async def upsert_daily_log(
    payload: DailyLogCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyLog:
    await _ensure_profile_exists(db, current_user_id)
    log_date = payload.log_date or date.today()

    # Find existing daily log for (user_id, log_date)
    stmt = (
        select(DailyLog)
        .where(DailyLog.user_id == current_user_id, DailyLog.log_date == log_date)
        .options(selectinload(DailyLog.symptoms))
    )
    res = await db.execute(stmt)
    daily_log = res.scalar_one_or_none()

    symptom_objects = [
        SymptomLog(symptom_type=item.symptom_type, severity=item.severity)
        for item in payload.symptoms
    ]

    if daily_log is None:
        daily_log = DailyLog(
            user_id=current_user_id,
            log_date=log_date,
            pain=payload.pain,
            mood=payload.mood.value if payload.mood else None,
            discharge=payload.discharge.value if payload.discharge else None,
            flow=payload.flow.value if payload.flow else None,
            notes=payload.notes,
            symptoms=symptom_objects,
        )
        db.add(daily_log)
    else:
        daily_log.pain = payload.pain
        daily_log.mood = payload.mood.value if payload.mood else None
        daily_log.discharge = payload.discharge.value if payload.discharge else None
        daily_log.flow = payload.flow.value if payload.flow else None
        daily_log.notes = payload.notes
        daily_log.symptoms = symptom_objects

    await db.commit()
    await db.refresh(daily_log, ["symptoms"])
    return daily_log


@router.patch(
    "/logs/{log_id}",
    response_model=DailyLogResponse,
    summary="Partially update a daily log entry",
    description=(
        "Partially updates an existing daily log entry. Only fields explicitly included in the request payload "
        "are modified. Explicitly passing null clears the corresponding optional field."
    ),
)
async def update_daily_log(
    log_id: int,
    payload: DailyLogUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyLog:
    stmt = (
        select(DailyLog)
        .where(DailyLog.id == log_id, DailyLog.user_id == current_user_id)
        .options(selectinload(DailyLog.symptoms))
    )
    res = await db.execute(stmt)
    daily_log = res.scalar_one_or_none()

    if not daily_log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily log not found")

    # Use model_fields_set to distinguish between unspecified fields and explicitly supplied nulls
    fields_set = payload.model_fields_set

    if "pain" in fields_set and payload.pain is not None:
        daily_log.pain = payload.pain
    if "mood" in fields_set:
        daily_log.mood = payload.mood.value if payload.mood else None
    if "discharge" in fields_set:
        daily_log.discharge = payload.discharge.value if payload.discharge else None
    if "flow" in fields_set:
        daily_log.flow = payload.flow.value if payload.flow else None
    if "notes" in fields_set:
        daily_log.notes = payload.notes

    if "symptoms" in fields_set:
        daily_log.symptoms = [
            SymptomLog(symptom_type=item.symptom_type, severity=item.severity)
            for item in (payload.symptoms or [])
        ]

    await db.commit()
    await db.refresh(daily_log, ["symptoms"])
    return daily_log
