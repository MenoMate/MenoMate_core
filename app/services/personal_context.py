"""Typed, user-isolated Personal Context Builder for MenoMate Care.

Assembles a compact PersonalCareContext from authenticated user records:
- Current cycle & historical cycle summary
- Recent daily logs (bounded window, never full DB dump)
- Longitudinal patterns & insights from pattern_engine
- Explicitly saved CareMemory preferences & context
- Device session & post-session feedback summary
- Explicit tracking completeness & missing-data notes

Never accepts a client-supplied user_id for authorization.
"""

import uuid
from datetime import timedelta
from typing import Dict, List, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.care_memory import CareMemory
from app.models.cycle import Cycle
from app.models.daily_log import DailyLog
from app.models.device import Device
from app.models.health_context import HealthCondition, Medication
from app.models.profile import Profile
from app.models.therapy_session import TherapySession
from app.schemas.care_context import (
    CycleHistorySummary,
    DailyLogSnapshot,
    DeviceSessionSummary,
    MemorySnapshot,
    PersonalCareContext,
)
from app.schemas.daily_log import decode_moods
from app.services.cycle_calculator import calculate_cycle_lengths
from app.services.pattern_engine import analyze_user_patterns, map_date_to_cycle
from app.services.summary import get_current_cycle_summary
from app.services.therapy_policy import calculate_therapy_recommendation
from app.services.timezone import user_today_for

MAX_RECENT_LOGS_IN_CONTEXT = 10
MAX_SESSIONS_IN_CONTEXT = 10
MAX_MEMORIES_IN_CONTEXT = 15
PATTERN_WINDOW_DAYS = 90


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
        if session.target_temperature_c <= 41.0:
            return "MODERATE"
        return "STRONG"
    return "MODERATE"


async def build_personal_care_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    intent: str = "wellness_help",
    topic: Optional[str] = None,
    window_days: int = PATTERN_WINDOW_DAYS,
) -> PersonalCareContext:
    """Build a compact, typed PersonalCareContext strictly for `user_id`."""
    summary = await get_current_cycle_summary(db, user_id)
    today = await user_today_for(db, user_id)

    prof_res = await db.execute(select(Profile).where(Profile.user_id == user_id))
    prof = prof_res.scalar_one_or_none()
    sensitivity = prof.sensitivity_index if prof else 1.0

    cycles_res = await db.execute(
        select(Cycle)
        .where(Cycle.user_id == user_id, Cycle.period_start <= today)
        .order_by(Cycle.period_start.asc())
    )
    cycles = list(cycles_res.scalars().all())
    completed_lengths = calculate_cycle_lengths(cycles, today=today)
    complete_count = sum(1 for c in cycles if c.period_end is not None)
    incomplete_count = sum(1 for c in cycles if c.period_end is None)

    cutoff = today - timedelta(days=window_days - 1)
    logs_res = await db.execute(
        select(DailyLog)
        .where(
            DailyLog.user_id == user_id,
            DailyLog.log_date >= cutoff,
            DailyLog.log_date <= today,
        )
        .order_by(desc(DailyLog.log_date))
        .options(selectinload(DailyLog.symptoms))
    )
    logs = list(logs_res.scalars().all())

    sessions_res = await db.execute(
        select(TherapySession)
        .where(TherapySession.user_id == user_id)
        .order_by(desc(TherapySession.started_at))
        .limit(15)
    )
    sessions = list(sessions_res.scalars().all())

    mem_res = await db.execute(
        select(CareMemory)
        .where(CareMemory.user_id == user_id, CareMemory.is_active.is_(True))
        .order_by(desc(CareMemory.updated_at))
        .limit(MAX_MEMORIES_IN_CONTEXT)
    )
    memories = list(mem_res.scalars().all())

    dev_res = await db.execute(select(Device.id).where(Device.user_id == user_id))
    devices_linked = len(list(dev_res.scalars().all()))

    cond_res = await db.execute(
        select(HealthCondition)
        .where(HealthCondition.user_id == user_id, HealthCondition.is_active.is_(True))
        .limit(10)
    )
    conditions = [
        (c.custom_label or c.code) for c in cond_res.scalars().all()
    ]

    med_res = await db.execute(
        select(Medication)
        .where(Medication.user_id == user_id, Medication.is_active.is_(True))
        .limit(10)
    )
    medications = [m.name for m in med_res.scalars().all()]

    analysis = analyze_user_patterns(
        cycles=cycles,
        logs=logs,
        sessions=sessions,
        today=today,
        window_days=window_days,
    )

    recent_logs_snapshots: List[DailyLogSnapshot] = []
    for l in logs[:MAX_RECENT_LOGS_IN_CONTEXT]:
        mapped = map_date_to_cycle(l.log_date, cycles, today)
        moods_list = decode_moods(l.mood) or []
        recent_logs_snapshots.append(
            DailyLogSnapshot(
                id=l.id,
                date=str(l.log_date),
                cycle_day=mapped[1] if mapped else None,
                pain=l.pain,
                mood="/".join(moods_list) if moods_list else None,
                moods=moods_list,
                flow=l.flow,
                discharge=l.discharge,
                symptoms=[
                    {"type": s.symptom_type, "severity": s.severity}
                    for s in (l.symptoms or [])
                ],
            )
        )

    session_snapshots = [
        DeviceSessionSummary(
            id=s.id,
            started_at=s.started_at.isoformat() if s.started_at else "",
            mode=s.mode,
            profile=_resolve_profile_label(s),
            requested_heat_level=s.requested_heat_level,
            requested_duration_minutes=s.requested_duration_minutes,
            vibration_mode=s.vibration_mode,
            command_status=s.command_status,
            ack_status=s.ack_status,
            session_status=s.session_status,
            pain_before=s.pain_before,
            pain_after=s.pain_after,
            feedback=s.feedback,
            comfort_rating=s.comfort_rating,
            noticed_improvement=s.noticed_improvement,
        )
        for s in sessions[:MAX_SESSIONS_IN_CONTEXT]
    ]

    # Pain-band therapy pattern (preserves existing Care composer compatibility)
    pattern_data: Dict[str, Dict] = {
        "mild_pain": {"sessions": 0, "successful_sessions": 0, "preferred_profile": None, "profiles": {}},
        "moderate_pain": {"sessions": 0, "successful_sessions": 0, "preferred_profile": None, "profiles": {}},
        "severe_pain": {"sessions": 0, "successful_sessions": 0, "preferred_profile": None, "profiles": {}},
    }
    for s in sessions:
        p = s.pain_before
        if p is None:
            continue
        cat = "mild_pain" if p <= 4 else ("moderate_pain" if p <= 7 else "severe_pain")
        prof_label = _resolve_profile_label(s)
        pattern_data[cat]["sessions"] += 1
        pattern_data[cat]["profiles"][prof_label] = pattern_data[cat]["profiles"].get(prof_label, 0) + 1
        is_helpful = (
            s.feedback == "just_right"
            or s.comfort_rating == "comfortable"
            or s.noticed_improvement is True
            or (s.pain_after is not None and s.pain_after < p)
        )
        if is_helpful:
            pattern_data[cat]["successful_sessions"] += 1

    recent_pattern = {}
    for cat, val in pattern_data.items():
        if val["sessions"] > 0:
            best_profile = max(val["profiles"], key=val["profiles"].get)
            recent_pattern[cat] = {
                "preferred_profile": best_profile,
                "successful_sessions": val["successful_sessions"],
                "total_sessions": val["sessions"],
            }

    today_log = next((l for l in logs if l.log_date == today), None)
    current_pain = (
        today_log.pain
        if (today_log is not None and today_log.pain is not None)
        else summary.get("recent_pain_avg")
    )
    recommendation = None
    if isinstance(current_pain, (int, float)):
        rec = calculate_therapy_recommendation(
            pain_score=int(round(current_pain)),
            sensitivity_index=sensitivity,
        )
        rec_profile = None
        if rec["vibration_mode"] != "off":
            temp = rec["target_temperature_c"] or 0
            rec_profile = (
                "GENTLE" if temp <= 38.0 else ("MODERATE" if temp <= 41.0 else "STRONG")
            )
        recommendation = {"profile": rec_profile, "pain_score": rec["pain_score"]}

    has_history = bool(cycles or logs or sessions or memories)
    history_note = (
        "Verified user longitudinal records are available."
        if has_history
        else "Insufficient user history recorded yet. Do not assume personal patterns or preferences."
    )

    return PersonalCareContext(
        intent=intent,
        topic=topic,
        cycle=CycleHistorySummary(
            has_data=bool(summary.get("has_data")),
            current_cycle_day=summary.get("current_cycle_day"),
            phase=summary.get("phase") or "unknown",
            is_bleeding=bool(summary.get("is_bleeding")),
            predicted_next_period=(
                str(summary.get("predicted_next_period"))
                if summary.get("predicted_next_period")
                else None
            ),
            days_until_next_period=summary.get("days_until_next_period"),
            prediction_confidence=summary.get("prediction_confidence"),
            prediction_source=summary.get("prediction_source"),
            recent_cycle_lengths=completed_lengths[-5:] if completed_lengths else [],
            usual_cycle_length=summary.get("average_cycle_length"),
            completed_cycle_count=complete_count,
            incomplete_cycle_count=incomplete_count,
        ),
        recent_logs=recent_logs_snapshots,
        frequent_symptoms=[f["symptom"] for f in analysis.frequent_symptoms],
        recent_pain_avg=summary.get("recent_pain_avg"),
        insights=analysis.insights,
        pain_trend=analysis.pain_trend,
        memories=[
            MemorySnapshot(
                id=m.id,
                category=m.category,
                key=m.key,
                value=m.value,
                source=m.source,
            )
            for m in memories
        ],
        health_conditions=conditions,
        medications=medications,
        devices_linked=devices_linked,
        recent_therapy_sessions=session_snapshots,
        device_preference_summary=analysis.device_preference_summary,
        recent_pattern=recent_pattern,
        recommendation=recommendation,
        sensitivity_index=sensitivity,
        tracking_completeness=analysis.tracking_completeness,
        has_history=has_history,
        history_note=history_note,
    )
