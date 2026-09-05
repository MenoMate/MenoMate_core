import uuid
from datetime import date, timedelta
from typing import Any, Dict, List
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.daily_log import DailyLog
from app.services.summary import get_current_cycle_summary


async def build_care_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    days_back: int = 3,
) -> Dict[str, Any]:
    """
    Assembles a compact, privacy-conscious context payload for Care AI inquiries.
    Includes current cycle day, estimated phase, predicted next period,
    and the last few days of symptom, mood, and discharge logs.
    """
    summary = await get_current_cycle_summary(db, user_id)
    today = date.today()
    cutoff = today - timedelta(days=days_back)

    # Fetch last 3-5 days of daily logs
    stmt = (
        select(DailyLog)
        .where(DailyLog.user_id == user_id, DailyLog.log_date >= cutoff)
        .order_by(desc(DailyLog.log_date))
        .options(selectinload(DailyLog.symptoms))
    )
    res = await db.execute(stmt)
    logs: List[DailyLog] = list(res.scalars().all())

    recent_logs = []
    for l in logs:
        recent_logs.append({
            "date": str(l.log_date),
            "pain": l.pain,
            "mood": l.mood,
            "discharge": l.discharge,
            "flow": l.flow,
            "symptoms": [s.symptom_type for s in l.symptoms],
        })

    return {
        "cycle_day": summary.get("current_cycle_day"),
        "phase": summary.get("phase"),
        "is_bleeding": summary.get("is_bleeding"),
        "predicted_next_period": str(summary.get("predicted_next_period")) if summary.get("predicted_next_period") else None,
        "prediction_confidence": summary.get("prediction_confidence"),
        "recent_logs": recent_logs,
    }
