from datetime import date, timedelta
import pytest
from app.services.cycle_engine import calculate_cycle_metrics, recalculate_user_cycle_average
from app.models.profile import Profile
from app.models.cycle import Cycle
import uuid


def test_calculate_cycle_metrics():
    start = date(2026, 1, 1)
    cycle_length_avg = 28
    today = date(2026, 1, 10)

    next_period, ovulation, cycle_day, days_left = calculate_cycle_metrics(
        start_date=start,
        cycle_length_avg=cycle_length_avg,
        today=today,
    )

    # Next period = 2026-01-01 + 28 = 2026-01-29
    assert next_period == date(2026, 1, 29)
    # Ovulation = 2026-01-29 - 14 = 2026-01-15
    assert ovulation == date(2026, 1, 15)
    # Cycle day = (Jan 10 - Jan 1) + 1 = 10
    assert cycle_day == 10
    # Days left = (Jan 29 - Jan 10) = 19
    assert days_left == 19


@pytest.mark.asyncio
async def test_recalculate_user_cycle_average(db_session):
    user_id = uuid.uuid4()
    profile = Profile(id=user_id, cycle_length_avg=28, period_length_avg=5)
    db_session.add(profile)
    await db_session.commit()

    # Add 3 completed cycles: 28 days, 30 days, 26 days (average = 28)
    c1 = Cycle(user_id=user_id, start_date=date(2025, 10, 1), end_date=date(2025, 10, 28), is_active=False) # 28 days
    c2 = Cycle(user_id=user_id, start_date=date(2025, 10, 29), end_date=date(2025, 11, 27), is_active=False) # 30 days
    c3 = Cycle(user_id=user_id, start_date=date(2025, 11, 28), end_date=date(2025, 12, 23), is_active=False) # 26 days

    db_session.add_all([c1, c2, c3])
    await db_session.commit()

    new_avg = await recalculate_user_cycle_average(db_session, user_id, limit=3)
    assert new_avg == 28
