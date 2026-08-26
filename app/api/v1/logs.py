import uuid
from datetime import date, timedelta
from typing import List
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.daily_log import DailyLog
from app.models.profile import Profile
from app.schemas.daily_log import DailyLogCreate, DailyLogResponse

router = APIRouter(prefix="/logs", tags=["Daily Logs & Symptoms"])


async def _ensure_profile_exists(db: AsyncSession, user_id: uuid.UUID) -> None:
    stmt = select(Profile).where(Profile.id == user_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none() is None:
        profile = Profile(id=user_id)
        db.add(profile)
        await db.commit()


@router.post(
    "/daily",
    response_model=DailyLogResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert daily symptom and cramp record",
)
async def upsert_daily_log(
    payload: DailyLogCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyLog:
    await _ensure_profile_exists(db, current_user_id)
    log_date = payload.log_date or date.today()

    stmt = select(DailyLog).where(
        DailyLog.user_id == current_user_id,
        DailyLog.log_date == log_date,
    )
    result = await db.execute(stmt)
    existing_log = result.scalar_one_or_none()

    if existing_log:
        existing_log.cramp_severity = payload.cramp_severity
        existing_log.flow_intensity = payload.flow_intensity.value
        existing_log.mood = payload.mood.value
        existing_log.symptoms = payload.symptoms
        existing_log.notes = payload.notes
        log_entry = existing_log
    else:
        log_entry = DailyLog(
            user_id=current_user_id,
            log_date=log_date,
            cramp_severity=payload.cramp_severity,
            flow_intensity=payload.flow_intensity.value,
            mood=payload.mood.value,
            symptoms=payload.symptoms,
            notes=payload.notes,
        )
        db.add(log_entry)

    await db.commit()
    await db.refresh(log_entry)
    return log_entry


@router.get(
    "/history",
    response_model=List[DailyLogResponse],
    summary="Fetch past days of symptom logs (default 30 days)",
)
async def get_log_history(
    days: int = Query(default=30, ge=1, le=365, description="Number of past days to retrieve"),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[DailyLog]:
    cutoff_date = date.today() - timedelta(days=days)
    stmt = (
        select(DailyLog)
        .where(
            DailyLog.user_id == current_user_id,
            DailyLog.log_date >= cutoff_date,
        )
        .order_by(desc(DailyLog.log_date))
    )
    result = await db.execute(stmt)
    logs = list(result.scalars().all())
    return logs
