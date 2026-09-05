import uuid
from datetime import date, datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.daily_log import DailyLog
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

    session = TherapySession(
        user_id=current_user_id,
        device_id=payload.device_id,
        started_at=payload.started_at or datetime.now(timezone.utc),
        ended_at=payload.ended_at,
        mode=payload.mode,
        target_temperature_c=payload.target_temperature_c,
        vibration_intensity=payload.vibration_intensity,
        vibration_mode=payload.vibration_mode,
        pain_before=payload.pain_before,
        pain_after=payload.pain_after,
        feedback=payload.feedback,
    )
    db.add(session)

    # Adjust sensitivity if feedback was provided
    if payload.feedback:
        new_sens, _ = adjust_sensitivity(profile.sensitivity_index, payload.feedback)
        profile.sensitivity_index = new_sens

    await db.commit()
    await db.refresh(session)
    return session


@router.patch(
    "/sessions/{session_id}",
    response_model=TherapySessionResponse,
    summary="Update therapy session feedback and tune adaptive sensitivity index",
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
        session.ended_at = payload.ended_at
    if payload.pain_after is not None:
        session.pain_after = payload.pain_after
    if payload.feedback is not None:
        session.feedback = payload.feedback
        profile = await _get_or_create_profile(db, current_user_id)
        new_sens, _ = adjust_sensitivity(profile.sensitivity_index, payload.feedback)
        profile.sensitivity_index = new_sens

    await db.commit()
    await db.refresh(session)
    return session
