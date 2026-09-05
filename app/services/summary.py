import uuid
from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.cycle import Cycle
from app.models.daily_log import DailyLog
from app.models.profile import Profile
from app.models.symptom_log import SymptomLog
from app.services.cycle_calculator import (
    calculate_cycle_lengths,
    calculate_period_length,
    estimate_phase,
    predict_next_cycle,
)


async def get_current_cycle_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    if today is None:
        today = date.today()

    # 1. Fetch user profile
    profile_stmt = select(Profile).where(Profile.user_id == user_id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    usual_cycle = profile.usual_cycle_days if profile else None
    usual_period = profile.usual_period_days if profile else 5

    # 2. Fetch all user periods ordered by start date ascending
    cycles_stmt = select(Cycle).where(Cycle.user_id == user_id).order_by(Cycle.period_start.asc())
    cycles_res = await db.execute(cycles_stmt)
    all_periods: List[Cycle] = list(cycles_res.scalars().all())

    # 3. Calculate completed cycle lengths & prediction
    cycle_lengths = calculate_cycle_lengths(all_periods)
    predicted_length, confidence, variability = predict_next_cycle(
        completed_cycle_lengths=cycle_lengths,
        usual_cycle_days=usual_cycle,
    )

    # 4. Determine latest period and current state
    if not all_periods:
        return {
            "has_data": False,
            "current_cycle_day": None,
            "phase": "unknown",
            "is_bleeding": False,
            "predicted_next_period": None,
            "days_until_next_period": None,
            "prediction_confidence": "insufficient_data",
            "average_cycle_length": usual_cycle,
            "average_period_length": usual_period,
            "today_log": None,
            "recent_pain_avg": None,
            "frequent_symptoms": [],
        }

    latest_period = all_periods[-1]
    is_bleeding = (latest_period.period_end is None) or (today <= latest_period.period_end)
    current_cycle_day = max(1, (today - latest_period.period_start).days + 1)
    
    predicted_next_period = latest_period.period_start + timedelta(days=predicted_length)
    days_until_next_period = (predicted_next_period - today).days

    # Calculate average period length
    completed_periods = [p for p in all_periods if p.period_end]
    if completed_periods:
        period_durations = [calculate_period_length(p) for p in completed_periods if calculate_period_length(p)]
        avg_period_len = round(sum(period_durations) / len(period_durations)) if period_durations else (usual_period or 5)
    else:
        avg_period_len = usual_period or 5

    phase = estimate_phase(
        cycle_day=current_cycle_day,
        cycle_length=predicted_length,
        is_bleeding=is_bleeding,
        period_length=avg_period_len,
    )

    avg_cycle_len = round(sum(cycle_lengths) / len(cycle_lengths)) if cycle_lengths else (usual_cycle or 28)

    # 5. Fetch today's daily log
    today_log_stmt = (
        select(DailyLog)
        .where(DailyLog.user_id == user_id, DailyLog.log_date == today)
        .options(selectinload(DailyLog.symptoms))
    )
    today_log_res = await db.execute(today_log_stmt)
    today_log = today_log_res.scalar_one_or_none()

    # 6. Fetch recent logs (past 14 days) for pain average and frequent symptoms
    recent_cutoff = today - timedelta(days=14)
    recent_logs_stmt = (
        select(DailyLog)
        .where(DailyLog.user_id == user_id, DailyLog.log_date >= recent_cutoff)
        .options(selectinload(DailyLog.symptoms))
    )
    recent_logs_res = await db.execute(recent_logs_stmt)
    recent_logs: List[DailyLog] = list(recent_logs_res.scalars().all())

    recent_pain_avg = None
    if recent_logs:
        pains = [log.pain for log in recent_logs]
        recent_pain_avg = round(sum(pains) / len(pains), 1)

    symptom_counter: Counter = Counter()
    for log in recent_logs:
        for s in log.symptoms:
            symptom_counter[s.symptom_type] += 1
    frequent_symptoms = [item[0] for item in symptom_counter.most_common(5)]

    return {
        "has_data": True,
        "current_cycle_day": current_cycle_day,
        "phase": phase,
        "is_bleeding": is_bleeding,
        "latest_period_start": latest_period.period_start,
        "latest_period_end": latest_period.period_end,
        "predicted_next_period": predicted_next_period,
        "days_until_next_period": days_until_next_period,
        "prediction_confidence": confidence,
        "average_cycle_length": avg_cycle_len,
        "average_period_length": avg_period_len,
        "today_log": today_log,
        "recent_pain_avg": recent_pain_avg,
        "frequent_symptoms": frequent_symptoms,
    }


async def get_history_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> Dict[str, Any]:
    # Fetch all periods sorted ascending
    stmt = select(Cycle).where(Cycle.user_id == user_id).order_by(Cycle.period_start.asc())
    res = await db.execute(stmt)
    periods: List[Cycle] = list(res.scalars().all())

    # Build historical period list with cycle length and period length
    history_entries = []
    cycle_lengths = calculate_cycle_lengths(periods)
    
    for i, p in enumerate(periods):
        p_len = calculate_period_length(p)
        c_len = None
        if i < len(periods) - 1:
            c_len = (periods[i + 1].period_start - p.period_start).days
        history_entries.append({
            "id": p.id,
            "period_start": p.period_start,
            "period_end": p.period_end,
            "period_length_days": p_len,
            "cycle_length_days": c_len,
        })

    # Historical periods ordered newest first for presentation
    history_entries.reverse()

    # All-time symptom frequency
    symptoms_stmt = (
        select(SymptomLog.symptom_type)
        .join(DailyLog, SymptomLog.daily_log_id == DailyLog.id)
        .where(DailyLog.user_id == user_id)
    )
    symp_res = await db.execute(symptoms_stmt)
    all_symp_types = symp_res.scalars().all()
    symptom_counts = dict(Counter(all_symp_types).most_common())

    avg_cycle = round(sum(cycle_lengths) / len(cycle_lengths), 1) if cycle_lengths else None
    period_lens = [calculate_period_length(p) for p in periods if calculate_period_length(p)]
    avg_period = round(sum(period_lens) / len(period_lens), 1) if period_lens else None

    # Variability std dev
    _, _, variability = predict_next_cycle(cycle_lengths)

    return {
        "total_periods_logged": len(periods),
        "average_cycle_length": avg_cycle,
        "average_period_length": avg_period,
        "cycle_variability_std_dev": variability,
        "history": history_entries,
        "symptom_frequencies": symptom_counts,
    }
