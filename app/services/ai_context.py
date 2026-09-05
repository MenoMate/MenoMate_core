import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cycle import Cycle
from app.models.daily_log import DailyLog
from app.models.profile import Profile
from app.models.therapy_session import TherapySession
from app.services.cycle_calculator import calculate_cycle_lengths
from app.services.summary import get_current_cycle_summary


async def build_care_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    intent: Optional[str] = None,
    days_back: int = 3,
) -> Dict[str, Any]:
    """
    Assembles a compact, intent-tailored, privacy-conscious context payload for Care AI inquiries.
    Intent-driven context selection:
    - 'cycle' / 'cycle_insight': cycle status, recent cycle lengths, usual cycle baseline.
    - 'therapy' / 'pain_help': recent therapy sessions, sensitivity index, recent pain ratings.
    - 'symptoms' / 'symptom_inquiry': recent daily symptom logs, frequent symptoms.
    - general / other: minimal compact summary.
    """
    summary = await get_current_cycle_summary(db, user_id)
    today = date.today()

    # --- Therapy Intent Context ---
    if intent in ("therapy", "pain_help"):
        # Fetch user sensitivity
        prof_stmt = select(Profile).where(Profile.user_id == user_id)
        prof_res = await db.execute(prof_stmt)
        prof = prof_res.scalar_one_or_none()
        sensitivity = prof.sensitivity_index if prof else 1.0

        # Fetch recent 3 therapy sessions
        therapy_stmt = (
            select(TherapySession)
            .where(TherapySession.user_id == user_id)
            .order_by(desc(TherapySession.started_at))
            .limit(3)
        )
        therapy_res = await db.execute(therapy_stmt)
        sessions = therapy_res.scalars().all()

        recent_sessions = [
            {
                "mode": s.mode,
                "target_temp_c": s.target_temperature_c,
                "vibration_intensity": s.vibration_intensity,
                "pain_before": s.pain_before,
                "pain_after": s.pain_after,
                "feedback": s.feedback,
            }
            for s in sessions
        ]

        return {
            "intent": intent,
            "cycle_day": summary.get("current_cycle_day"),
            "phase": summary.get("phase"),
            "recent_pain_avg": summary.get("recent_pain_avg"),
            "sensitivity_index": sensitivity,
            "recent_therapy_sessions": recent_sessions,
        }

    # --- Cycle Inquiry Context ---
    if intent in ("cycle", "cycle_insight"):
        cycles_stmt = select(Cycle).where(Cycle.user_id == user_id).order_by(Cycle.period_start.asc())
        cycles_res = await db.execute(cycles_stmt)
        all_periods = list(cycles_res.scalars().all())
        completed_lengths = calculate_cycle_lengths(all_periods)

        return {
            "intent": intent,
            "cycle_day": summary.get("current_cycle_day"),
            "phase": summary.get("phase"),
            "is_bleeding": summary.get("is_bleeding"),
            "predicted_next_period": str(summary.get("predicted_next_period")) if summary.get("predicted_next_period") else None,
            "days_until_next_period": summary.get("days_until_next_period"),
            "prediction_confidence": summary.get("prediction_confidence"),
            "prediction_source": summary.get("prediction_source"),
            "recent_cycle_lengths": completed_lengths[-3:] if completed_lengths else [],
            "usual_cycle_length": summary.get("average_cycle_length"),
        }

    # --- Symptom Inquiry Context ---
    if intent in ("symptom_insight", "symptoms", "symptom_inquiry"):
        cutoff = today - timedelta(days=max(days_back, 7))
        stmt = (
            select(DailyLog)
            .where(DailyLog.user_id == user_id, DailyLog.log_date >= cutoff)
            .order_by(desc(DailyLog.log_date))
            .options(selectinload(DailyLog.symptoms))
        )
        res = await db.execute(stmt)
        logs: List[DailyLog] = list(res.scalars().all())

        recent_logs = [
            {
                "date": str(l.log_date),
                "pain": l.pain,
                "mood": l.mood,
                "discharge": l.discharge,
                "flow": l.flow,
                "symptoms": [s.symptom_type for s in l.symptoms],
            }
            for l in logs
        ]

        return {
            "intent": intent,
            "cycle_day": summary.get("current_cycle_day"),
            "phase": summary.get("phase"),
            "frequent_symptoms": summary.get("frequent_symptoms", []),
            "recent_logs": recent_logs,
        }

    # --- Default / General Wellness Context (Minimal) ---
    return {
        "intent": intent or "general_wellness",
        "cycle_day": summary.get("current_cycle_day"),
        "phase": summary.get("phase"),
        "is_bleeding": summary.get("is_bleeding"),
        "predicted_next_period": str(summary.get("predicted_next_period")) if summary.get("predicted_next_period") else None,
        "prediction_confidence": summary.get("prediction_confidence"),
        "recent_pain_avg": summary.get("recent_pain_avg"),
    }
