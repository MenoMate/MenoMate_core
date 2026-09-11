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

    # --- Therapy / Pain Personalization Intent Context ---
    if intent in ("therapy", "pain_help", "therapy_recommendation"):
        # Fetch user sensitivity
        prof_stmt = select(Profile).where(Profile.user_id == user_id)
        prof_res = await db.execute(prof_stmt)
        prof = prof_res.scalar_one_or_none()
        sensitivity = prof.sensitivity_index if prof else 1.0

        # Query up to 10 recent therapy sessions for verified behavioral patterns
        therapy_stmt = (
            select(TherapySession)
            .where(TherapySession.user_id == user_id)
            .order_by(desc(TherapySession.started_at))
            .limit(10)
        )
        therapy_res = await db.execute(therapy_stmt)
        sessions = list(therapy_res.scalars().all())

        # Check today's pain
        today_log_stmt = select(DailyLog).where(DailyLog.user_id == user_id, DailyLog.log_date == today)
        today_log_res = await db.execute(today_log_stmt)
        today_log = today_log_res.scalar_one_or_none()
        current_pain = today_log.pain if today_log else summary.get("recent_pain_avg")

        has_history = len(sessions) > 0
        recent_feedback = [s.feedback for s in sessions if s.feedback][:5]

        # Analyze verified behavioral patterns per pain category (mild: 1-4, moderate: 5-7, severe: 8-10)
        pattern_data: Dict[str, Dict[str, Any]] = {
            "mild_pain": {"sessions": 0, "successful_sessions": 0, "preferred_profile": None, "profiles": {}},
            "moderate_pain": {"sessions": 0, "successful_sessions": 0, "preferred_profile": None, "profiles": {}},
            "severe_pain": {"sessions": 0, "successful_sessions": 0, "preferred_profile": None, "profiles": {}},
        }

        def _resolve_profile_label(session: TherapySession) -> str:
            mode_lower = (session.mode or "").lower()
            if "gentle" in mode_lower:
                return "GENTLE"
            if "strong" in mode_lower or "intense" in mode_lower:
                return "STRONG"
            if "mod" in mode_lower:
                return "MODERATE"
            if session.target_temperature_c is not None:
                if session.target_temperature_c <= 38.0:
                    return "GENTLE"
                elif session.target_temperature_c <= 41.0:
                    return "MODERATE"
                else:
                    return "STRONG"
            return "MODERATE"

        for s in sessions:
            p = s.pain_before
            if p is None:
                continue
            cat = "mild_pain" if p <= 4 else ("moderate_pain" if p <= 7 else "severe_pain")
            prof_label = _resolve_profile_label(s)
            pattern_data[cat]["sessions"] += 1
            pattern_data[cat]["profiles"][prof_label] = pattern_data[cat]["profiles"].get(prof_label, 0) + 1
            is_successful = (s.feedback == "just_right") or (s.pain_after is not None and s.pain_after < p)
            if is_successful:
                pattern_data[cat]["successful_sessions"] += 1

        recent_pattern = {}
        for cat, val in pattern_data.items():
            if val["sessions"] > 0:
                best_profile = max(val["profiles"], key=val["profiles"].get) if val["profiles"] else None
                recent_pattern[cat] = {
                    "preferred_profile": best_profile,
                    "successful_sessions": val["successful_sessions"],
                    "total_sessions": val["sessions"],
                }

        recent_sessions = [
            {
                "mode": s.mode,
                "profile": _resolve_profile_label(s),
                "target_temp_c": s.target_temperature_c,
                "vibration_intensity": s.vibration_intensity,
                "pain_before": s.pain_before,
                "pain_after": s.pain_after,
                "feedback": s.feedback,
            }
            for s in sessions[:3]
        ]

        return {
            "intent": intent,
            "cycle_day": summary.get("current_cycle_day"),
            "phase": summary.get("phase"),
            "current_pain": current_pain,
            "recent_pain_avg": summary.get("recent_pain_avg"),
            "sensitivity_index": sensitivity,
            "has_history": has_history,
            "history_note": (
                "Verified user therapy history is available."
                if has_history
                else "No prior therapy sessions recorded. State that there is insufficient history to personalize recommendations."
            ),
            "recent_pattern": recent_pattern,
            "recent_feedback": recent_feedback,
            "recent_therapy_sessions": recent_sessions,
        }

    # --- Cycle Inquiry Context ---
    if intent in ("cycle", "cycle_insight"):
        cycles_stmt = select(Cycle).where(Cycle.user_id == user_id).order_by(Cycle.period_start.asc())
        cycles_res = await db.execute(cycles_stmt)
        all_periods = list(cycles_res.scalars().all())
        completed_lengths = calculate_cycle_lengths(all_periods, today=today)

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
