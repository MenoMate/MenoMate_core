import uuid
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
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
    TherapySessionFeedbackUpdate,
    TherapySessionResponse,
)
from app.services.calibrator import (
    adjust_sensitivity_on_feedback,
    generate_recommendation,
)

router = APIRouter(prefix="/therapy", tags=["Therapy & Recommendation Engine"])


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


@router.post(
    "/recommend",
    response_model=TherapyRecommendationResponse,
    summary="Generate personalized hardware thermal and vibration parameters",
)
async def get_therapy_recommendation(
    payload: TherapyRecommendationRequest = TherapyRecommendationRequest(),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TherapyRecommendationResponse:
    profile = await _get_or_create_profile(db, current_user_id)

    severity: int = 0
    if payload.cramp_severity is not None:
        severity = payload.cramp_severity
    else:
        # Check today's daily log or latest log
        today = date.today()
        stmt = (
            select(DailyLog)
            .where(DailyLog.user_id == current_user_id, DailyLog.log_date == today)
            .limit(1)
        )
        result = await db.execute(stmt)
        today_log = result.scalar_one_or_none()

        if today_log is not None:
            severity = today_log.cramp_severity
        else:
            # Fallback to the latest logged entry
            latest_stmt = (
                select(DailyLog)
                .where(DailyLog.user_id == current_user_id)
                .order_by(desc(DailyLog.log_date))
                .limit(1)
            )
            latest_res = await db.execute(latest_stmt)
            latest_log = latest_res.scalar_one_or_none()
            if latest_log:
                severity = latest_log.cramp_severity

    recommendation = generate_recommendation(
        cramp_severity=severity,
        sensitivity_index=profile.sensitivity_index,
    )
    return recommendation


@router.post(
    "/session",
    response_model=TherapySessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a completed hardware therapy session log",
)
async def log_therapy_session(
    payload: TherapySessionCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TherapySession:
    profile = await _get_or_create_profile(db, current_user_id)

    session = TherapySession(
        user_id=current_user_id,
        timestamp=payload.timestamp or datetime.now(timezone.utc),
        target_temp_celsius=payload.target_temp_celsius,
        vibration_mode=payload.vibration_mode.value,
        vibration_intensity=payload.vibration_intensity,
        duration_minutes=payload.duration_minutes,
        pre_cramp_score=payload.pre_cramp_score,
        post_relief_score=payload.post_relief_score,
        feedback_tag=payload.feedback_tag.value if payload.feedback_tag else None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # If feedback was included on creation, update sensitivity
    if payload.feedback_tag:
        new_sensitivity, _ = adjust_sensitivity_on_feedback(
            current_sensitivity=profile.sensitivity_index,
            feedback_tag=payload.feedback_tag,
        )
        profile.sensitivity_index = new_sensitivity
        await db.commit()

    return session


@router.patch(
    "/session/{session_id}/feedback",
    response_model=TherapySessionResponse,
    summary="Update post-therapy feedback and adjust adaptive sensitivity index",
)
async def update_session_feedback(
    session_id: int,
    payload: TherapySessionFeedbackUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TherapySession:
    stmt = select(TherapySession).where(
        TherapySession.id == session_id,
        TherapySession.user_id == current_user_id,
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Therapy session not found",
        )

    session.feedback_tag = payload.feedback_tag.value
    if payload.post_relief_score is not None:
        session.post_relief_score = payload.post_relief_score

    # Adjust profile sensitivity
    profile = await _get_or_create_profile(db, current_user_id)
    new_sensitivity, _ = adjust_sensitivity_on_feedback(
        current_sensitivity=profile.sensitivity_index,
        feedback_tag=payload.feedback_tag,
    )
    profile.sensitivity_index = new_sensitivity

    await db.commit()
    await db.refresh(session)

    return session
