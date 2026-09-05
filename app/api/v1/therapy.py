import uuid
from datetime import date, datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.daily_log import DailyLog
from app.models.device import Device
from app.models.profile import Profile
from app.models.therapy_session import TherapySession
from app.schemas.therapy import (
    TherapyRecommendationRequest,
    TherapyRecommendationResponse,
    TherapySessionCreate,
    TherapySessionResponse,
    TherapySessionUpdate,
)
from app.services.therapy_policy import (
    adjust_sensitivity,
    calculate_therapy_recommendation,
)

router = APIRouter(prefix="/therapy", tags=["Therapy Controls"])


def _normalize_dt(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def _get_or_create_profile(db: AsyncSession, user_id: uuid.UUID) -> Profile:
    stmt = select(Profile).where(Profile.user_id == user_id)
    res = await db.execute(stmt)
    profile = res.scalar_one_or_none()
    if not profile:
        profile = Profile(user_id=user_id)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
    return profile


@router.post(
    "/recommend",
    response_model=TherapyRecommendationResponse,
    summary="Generate deterministic hardware thermal and vibration recommendation",
)
async def recommend_therapy(
    payload: TherapyRecommendationRequest = TherapyRecommendationRequest(),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TherapyRecommendationResponse:
    profile = await _get_or_create_profile(db, current_user_id)

    pain = 0
    if payload.pain_score is not None:
        pain = payload.pain_score
    else:
        # Check today's logged pain
        today = date.today()
        stmt = select(DailyLog).where(
            DailyLog.user_id == current_user_id, DailyLog.log_date == today
        )
        res = await db.execute(stmt)
        today_log = res.scalar_one_or_none()
        if today_log:
            pain = today_log.pain

    rec = calculate_therapy_recommendation(
        pain_score=pain,
        sensitivity_index=profile.sensitivity_index,
    )
    return TherapyRecommendationResponse(**rec)


@router.get(
    "/sessions",
    response_model=List[TherapySessionResponse],
    summary="List all wearable therapy sessions for user",
)
async def list_therapy_sessions(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[TherapySession]:
    stmt = (
        select(TherapySession)
        .where(TherapySession.user_id == current_user_id)
        .order_by(TherapySession.started_at.desc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post(
    "/sessions",
    response_model=TherapySessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a completed wearable therapy session",
)
async def log_therapy_session(
    payload: TherapySessionCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TherapySession:
    profile = await _get_or_create_profile(db, current_user_id)

    # 1. Device ownership check
    if payload.device_id is not None:
        device_stmt = select(Device).where(
            Device.id == payload.device_id,
            Device.user_id == current_user_id,
        )
        device_res = await db.execute(device_stmt)
        device = device_res.scalar_one_or_none()
        if not device:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Device not found or not owned by authenticated user",
            )

    # 2. Therapy session date validation
    started_at = payload.started_at or datetime.now(timezone.utc)
    if payload.ended_at and _normalize_dt(payload.ended_at) < _normalize_dt(started_at):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ended_at cannot be prior to started_at",
        )

    fb_val = payload.feedback.value if payload.feedback else None

    session = TherapySession(
        user_id=current_user_id,
        device_id=payload.device_id,
        started_at=started_at,
        ended_at=payload.ended_at,
        mode=payload.mode,
        target_temperature_c=payload.target_temperature_c,
        vibration_intensity=payload.vibration_intensity,
        vibration_mode=payload.vibration_mode,
        pain_before=payload.pain_before,
        pain_after=payload.pain_after,
        feedback=fb_val,
    )
    db.add(session)

    # Adjust sensitivity if feedback was provided
    if fb_val:
        new_sens, _ = adjust_sensitivity(profile.sensitivity_index, fb_val)
        profile.sensitivity_index = new_sens

    await db.commit()
    await db.refresh(session)
    return session


@router.patch(
    "/sessions/{session_id}",
    response_model=TherapySessionResponse,
    summary="Update therapy session feedback and tune adaptive sensitivity index",
    description="Updates therapy session feedback and tunes sensitivity index once. Subsequent feedback edits update the record without repeated sensitivity adjustment.",
)
async def update_therapy_session(
    session_id: int,
    payload: TherapySessionUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TherapySession:
    stmt = select(TherapySession).where(
        TherapySession.id == session_id,
        TherapySession.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Therapy session not found")

    if payload.ended_at is not None:
        if session.started_at and _normalize_dt(payload.ended_at) < _normalize_dt(session.started_at):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ended_at cannot be prior to started_at",
            )
        session.ended_at = payload.ended_at

    if payload.pain_after is not None:
        session.pain_after = payload.pain_after

    if payload.feedback is not None:
        fb_val = payload.feedback.value if hasattr(payload.feedback, "value") else str(payload.feedback)
        # Prevent double-application: only adjust sensitivity if this session had no feedback set yet
        if session.feedback is None:
            profile = await _get_or_create_profile(db, current_user_id)
            new_sens, _ = adjust_sensitivity(profile.sensitivity_index, fb_val)
            profile.sensitivity_index = new_sens
        session.feedback = fb_val

    await db.commit()
    await db.refresh(session)
    return session
