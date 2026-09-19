import uuid
from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.cycle import Cycle
    from app.models.daily_log import DailyLog
    from app.models.device import Device
    from app.models.fertility_observation import FertilityObservation
    from app.models.health_context import HealthCondition, HealthContext, Medication
    from app.models.pregnancy_context import PregnancyContext
    from app.models.therapy_session import TherapySession
    from app.models.reproductive_aging import ReproductiveAgingContext


class Profile(Base):
    __tablename__ = "profiles"

    # User ID matches Supabase auth.users.id
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
    )
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    usual_cycle_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usual_period_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    theme: Mapped[str] = mapped_column(String(32), default="system", nullable=False)
    units: Mapped[str] = mapped_column(String(32), default="metric", nullable=False)
    # Canonical IANA timezone identifier for user-local calendar semantics
    # (e.g. "Asia/Kolkata"). NULL only for legacy users until the device
    # persists it; see app.services.timezone. Never an offset/abbreviation.
    timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Optional date of birth at month/year precision only. Both columns are
    # always set or cleared together (enforced in the profile route); the
    # server never infers age from incomplete information.
    birth_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    birth_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sensitivity_index: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
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

    # Relationships with cascade delete on account deletion
    cycles: Mapped[List["Cycle"]] = relationship(
        "Cycle", back_populates="user", cascade="all, delete-orphan"
    )
    daily_logs: Mapped[List["DailyLog"]] = relationship(
        "DailyLog", back_populates="user", cascade="all, delete-orphan"
    )
    devices: Mapped[List["Device"]] = relationship(
        "Device", back_populates="user", cascade="all, delete-orphan"
    )
    therapy_sessions: Mapped[List["TherapySession"]] = relationship(
        "TherapySession", back_populates="user", cascade="all, delete-orphan"
    )
    health_context: Mapped[Optional["HealthContext"]] = relationship(
        "HealthContext", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    health_conditions: Mapped[List["HealthCondition"]] = relationship(
        "HealthCondition", back_populates="user", cascade="all, delete-orphan"
    )
    medications: Mapped[List["Medication"]] = relationship(
        "Medication", back_populates="user", cascade="all, delete-orphan"
    )
    fertility_observations: Mapped[List["FertilityObservation"]] = relationship(
        "FertilityObservation", back_populates="user", cascade="all, delete-orphan"
    )
    pregnancy_context: Mapped[Optional["PregnancyContext"]] = relationship(
        "PregnancyContext", back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    reproductive_aging_context: Mapped[Optional["ReproductiveAgingContext"]] = relationship(
        "ReproductiveAgingContext",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
