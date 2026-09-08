import asyncio
import datetime
import uuid
from app.db.session import async_session_factory
from sqlalchemy import select, desc
from app.models.cycle import Cycle
from app.schemas.cycle import CycleCreate, CycleUpdate
from app.api.v1.cycles import end_current_cycle, create_cycle

async def test_backend_handlers():
    test_user_id = uuid.UUID("7521eccc-f04c-45f5-b59d-7a1d7ad4b1ee")
    today = datetime.date(2026, 9, 8)

    async with async_session_factory() as db:
        print("=== STEP 1: Verify ongoing cycle exists ===")
        stmt = (
            select(Cycle)
            .where(Cycle.user_id == test_user_id, Cycle.period_end.is_(None))
            .order_by(desc(Cycle.period_start))
        )
        res = await db.execute(stmt)
        ongoing = res.scalar_one_or_none()
        print(f"Ongoing cycle before test: ID={ongoing.id if ongoing else None}, start={ongoing.period_start if ongoing else None}, end={ongoing.period_end if ongoing else None}")
        assert ongoing is not None, "Expected an ongoing cycle"

        print("\n=== STEP 2: Execute end_current_period (POST /api/v1/cycles/current/end) ===")
        end_req = CycleUpdate(period_end=today)
        ended_cycle = await end_current_cycle(payload=end_req, current_user_id=test_user_id, db=db)
        print(f"Ended cycle response: ID={ended_cycle.id}, start={ended_cycle.period_start}, end={ended_cycle.period_end}")
        assert ended_cycle.period_end == today, "Expected period_end to be today"

        # Verify no ongoing cycle remains
        res_check = await db.execute(stmt)
        assert res_check.scalar_one_or_none() is None, "Expected no ongoing cycle after end"
        print("PASS: Ongoing cycle successfully ended and verified in DB.")

        print("\n=== STEP 3: Execute create_cycle (POST /api/v1/cycles) ===")
        start_req = CycleCreate(period_start=today)
        new_cycle = await create_cycle(payload=start_req, current_user_id=test_user_id, db=db)
        print(f"Started cycle response: ID={new_cycle.id}, start={new_cycle.period_start}, end={new_cycle.period_end}")
        assert new_cycle.period_start == today
        assert new_cycle.period_end is None

        # Verify ongoing cycle exists again
        res_check2 = await db.execute(stmt)
        ongoing_again = res_check2.scalar_one_or_none()
        assert ongoing_again is not None, "Expected ongoing cycle after start"
        print(f"PASS: New cycle successfully started: ID={ongoing_again.id}, start={ongoing_again.period_start}, end={ongoing_again.period_end}")

if __name__ == "__main__":
    asyncio.run(test_backend_handlers())
