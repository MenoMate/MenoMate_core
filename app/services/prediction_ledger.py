"""
Phase 3 prediction instrumentation. Observational only.

- `maybe_record_served_prediction` snapshots a served model prediction into
  the ledger (called from the summary service; the serving route commits).
- `resolve_for_new_start` resolves the most recent open entry when the
  actual next period start is logged (called from cycle creation).

Neither function alters predictions, confidences, or API responses.
"""
import uuid
from datetime import date
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prediction_ledger import PredictionLedger

# Frozen production predictor identity. Bump ONLY when the served predictor
# itself changes; the walk-forward harness uses this as the baseline label.
BASELINE_METHOD = "robust_wma_v1"

# Sources emitted by the model predictor. Display-only user overrides
# (e.g. "user_logged" future dates) are not model predictions: never ledger.
MODEL_SOURCES = ("history", "usual_cycle")


async def maybe_record_served_prediction(
    db: AsyncSession,
    user_id: uuid.UUID,
    predicted_at: date,
    predicted_cycle_length: Optional[int],
    predicted_next_period: Optional[date],
    confidence: str,
    source: str,
    basis_start: Optional[date],
    basis_intervals: int,
    variability: Optional[float],
    basis_usual: Optional[int] = None,
    method: str = BASELINE_METHOD,
) -> Optional[PredictionLedger]:
    """
    Snapshot one served model prediction. Returns the entry, or None when
    there is nothing recordable (no prediction, non-model source, no anchor).

    Flushes but does NOT commit: the serving route owns the transaction.
    """
    if predicted_cycle_length is None or predicted_next_period is None:
        return None
    if source not in MODEL_SOURCES:
        return None
    if basis_start is None:
        return None
    entry = PredictionLedger(
        user_id=user_id,
        predicted_at=predicted_at,
        method=method,
        predicted_cycle_length=predicted_cycle_length,
        predicted_next_period=predicted_next_period,
        confidence=confidence,
        source=source,
        basis_start=basis_start,
        basis_intervals=basis_intervals,
        basis_usual=basis_usual,
        variability=variability,
    )
    db.add(entry)
    await db.flush()
    return entry


async def resolve_for_new_start(
    db: AsyncSession,
    user_id: uuid.UUID,
    new_start: date,
) -> list[PredictionLedger]:
    """
    Resolve EVERY open ledger entry anchored strictly before the newly
    logged period start. Each entry keeps its own served prediction and gets
    the same actual start with its own independent signed error in days
    (actual - predicted). Repeated servings of one upcoming prediction thus
    all resolve, preserving prediction-evolution data; rows are never
    deleted or collapsed.

    Idempotent: already-resolved rows never qualify again, so a repeated
    call resolves nothing further. Returns the newly resolved entries
    (empty list when none qualify). Flushes but does NOT commit.
    """
    stmt = (
        select(PredictionLedger)
        .where(
            PredictionLedger.user_id == user_id,
            PredictionLedger.resolved_actual_start.is_(None),
            PredictionLedger.basis_start < new_start,
        )
        .order_by(PredictionLedger.predicted_at, PredictionLedger.id)
    )
    res = await db.execute(stmt)
    entries = list(res.scalars().all())
    for entry in entries:
        entry.resolved_actual_start = new_start
        if entry.predicted_next_period is not None:
            entry.error_days = (new_start - entry.predicted_next_period).days
    if entries:
        await db.flush()
    return entries
