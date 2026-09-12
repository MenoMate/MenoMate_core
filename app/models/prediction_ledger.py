import uuid
from datetime import date, datetime, timezone
from typing import Optional
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class PredictionLedger(Base):
    """
    Phase 3 prediction instrumentation. Observational only.

    One row per served model prediction: what was predicted, as of which day,
    by which predictor method version, anchored to which period start. The
    row is resolved later when the actual next period start is observed, which
    yields the signed prediction error in days.

    This table NEVER influences predictions or API responses. It exists solely
    to support chronological evaluation, method/version comparison, prediction
    resolution, error measurement, and later confidence calibration.
    """
    __tablename__ = "prediction_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    # The as-of day the prediction was served (chronological evaluation key).
    predicted_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Predictor identity, e.g. "robust_wma_v1" (method/version comparison).
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    predicted_cycle_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    predicted_next_period: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # Anchor: the period start the prediction was counted from.
    basis_start: Mapped[date] = mapped_column(Date, nullable=False)
    # Number of observed intervals the prediction was trained on.
    basis_intervals: Mapped[int] = mapped_column(Integer, nullable=False)
    # User's stated usual_cycle_days exactly as it was at serve time.
    # NULL when no baseline exists. Never reconstructed from profiles later.
    basis_usual: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Robust variability (MAD, days) behind the served confidence label.
    variability: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Resolution: filled when the actual next period start is observed.
    resolved_actual_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Signed error in days: (actual_start - predicted_next_period).
    error_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
