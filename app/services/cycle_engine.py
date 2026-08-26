import uuid
from datetime import date, timedelta
from typing import List, Optional, Tuple
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cycle import Cycle
from app.models.profile import Profile


def calculate_cycle_metrics(
    start_date: date,
    cycle_length_avg: int = 28,
    today: Optional[date] = None,
) -> Tuple[date, date, int, int]:
    """
    Computes cycle projections from start_date and average cycle length.
    Returns (predicted_next_period, predicted_ovulation, current_cycle_day, days_until_next_period).
    """
    if today is None:
        today = date.today()

    predicted_next_period = start_date + timedelta(days=cycle_length_avg)
    predicted_ovulation = predicted_next_period - timedelta(days=14)
    
    current_cycle_day = (today - start_date).days + 1
    days_until_next_period = (predicted_next_period - today).days

    return predicted_next_period, predicted_ovulation, current_cycle_day, days_until_next_period


async def recalculate_user_cycle_average(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 3,
) -> Optional[int]:
    """
    Computes the rolling mean of the last `limit` (default 3) completed cycles
    and updates the user's profile.cycle_length_avg.
    """
    # Fetch last completed cycles with both start_date and end_date
    stmt = (
        select(Cycle)
        .where(
            Cycle.user_id == user_id,
            Cycle.end_date.is_not(None),
            Cycle.is_active == False,  # noqa: E712
        )
        .order_by(desc(Cycle.end_date))
        .limit(limit)
    )
    result = await db.execute(stmt)
    completed_cycles: List[Cycle] = list(result.scalars().all())

    if not completed_cycles:
        return None

    durations: List[int] = []
    for c in completed_cycles:
        if c.end_date and c.start_date:
            # Cycle duration in days (inclusive span: start to end inclusive)
            duration = (c.end_date - c.start_date).days + 1
            if duration > 0:
                durations.append(duration)

    if not durations:
        return None

    new_avg = round(sum(durations) / len(durations))
    # Clamp to healthy boundaries (20 - 45 days)
    new_avg = max(20, min(45, new_avg))

    # Update profile
    profile_stmt = select(Profile).where(Profile.id == user_id)
    profile_res = await db.execute(profile_stmt)
    profile = profile_res.scalar_one_or_none()
    if profile:
        profile.cycle_length_avg = new_avg
        await db.flush()

    return new_avg
