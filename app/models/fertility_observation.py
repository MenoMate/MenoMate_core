import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


# Closed vocabularies for Phase 2 fertility observations. The mucus taxonomy
# (dry/sticky/creamy/watery/egg_white) is the placeholder set from the
# approved Phase 1 design contract; it ships as an explicit versioned enum
# pending clinical sign-off (see final Phase 2 report). Only the enum values
# would change under review — never the table shape.
OBSERVATION_TYPES = ("lh_test", "bbt", "cervical_mucus")
LH_RESULTS = ("positive", "negative", "invalid")
MUCUS_CATEGORIES = ("dry", "sticky", "creamy", "watery", "egg_white")
OBSERVATION_SOURCES = ("manual", "imported")


class FertilityObservation(Base):
    """
    One user-measured fertility fact per user/day/type (OBSERVED data).

    This table is deliberately separate from `daily_logs.discharge` (a generic
    volume scale) and from `symptom_logs` (fixed 11-id taxonomy with 0-10
    severity). Observations carry NO confidence, method version, or window
    dates: they are the evidence that fertility estimates cite.

    - `observation_date` is a USER-LOCAL calendar DATE (never shifted).
    - An LH row records the test result only; it never claims ovulation
      occurred. BBT rows record the measured temperature only. Mucus rows
      record the observed category only.
    - Exactly one value column matches `observation_type` (CHECK-enforced).
    """

    __tablename__ = "fertility_observations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "observation_date",
            "observation_type",
            name="uq_fertility_obs_user_date_type",
        ),
        Index("idx_fertility_obs_user_date", "user_id", "observation_date"),
        CheckConstraint(
            "observation_type IN ('lh_test', 'bbt', 'cervical_mucus')",
            name="ck_fertility_obs_type",
        ),
        CheckConstraint(
            "((observation_type = 'lh_test' AND lh_result IS NOT NULL "
            "AND bbt_celsius IS NULL AND mucus_category IS NULL) "
            "OR (observation_type = 'bbt' AND bbt_celsius IS NOT NULL "
            "AND lh_result IS NULL AND mucus_category IS NULL) "
            "OR (observation_type = 'cervical_mucus' AND mucus_category IS NOT NULL "
            "AND lh_result IS NULL AND bbt_celsius IS NULL))",
            name="ck_fertility_obs_value_matches_type",
        ),
        CheckConstraint(
            "lh_result IS NULL OR lh_result IN ('positive', 'negative', 'invalid')",
            name="ck_fertility_obs_lh",
        ),
        CheckConstraint(
            "bbt_celsius IS NULL OR (bbt_celsius >= 35.00 AND bbt_celsius <= 42.00)",
            name="ck_fertility_obs_bbt_range",
        ),
        CheckConstraint(
            "mucus_category IS NULL OR mucus_category IN "
            "('dry', 'sticky', 'creamy', 'watery', 'egg_white')",
            name="ck_fertility_obs_mucus",
        ),
        CheckConstraint(
            "source IN ('manual', 'imported')",
            name="ck_fertility_obs_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    observation_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    observation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    lh_result: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    bbt_celsius: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 2), nullable=True)
    mucus_category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["Profile"] = relationship("Profile", back_populates="fertility_observations")
