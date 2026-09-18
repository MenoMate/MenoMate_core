"""Phase 4 reproductive-aging context persistence (explicit user control only).

All writes are explicit authenticated user actions storing verbatim free
text. Nothing here classifies, stages, or diagnoses reproductive aging,
perimenopause, menopause, or postmenopause; nothing here derives state from
cycle history, age, symptoms, observations, or predictions; and nothing here
touches the frozen period predictor, the prediction ledger, the backtest
harness, the timezone implementation, Health Context semantics, fertility
estimates, or pregnancy mode.
"""

import uuid
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reproductive_aging import ReproductiveAgingContext
from app.services.profile import get_or_create_profile


async def get_aging_row(
    db: AsyncSession, user_id: uuid.UUID
) -> Optional[ReproductiveAgingContext]:
    res = await db.execute(
        select(ReproductiveAgingContext).where(
            ReproductiveAgingContext.user_id == user_id
        )
    )
    return res.scalar_one_or_none()


async def apply_aging_put(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    notes: Optional[str],
) -> ReproductiveAgingContext:
    """Full-replacement upsert: notes is set verbatim from the payload
    (omitted -> null clears the recorded context). Creates the singleton
    row on first sync. Never reads or writes any other table."""
    await get_or_create_profile(db, user_id)
    row = await get_aging_row(db, user_id)
    if row is None:
        row = ReproductiveAgingContext(user_id=user_id)
        db.add(row)
    row.notes = notes
    await db.commit()
    await db.refresh(row)
    return row
