import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


class HealthContext(Base):
    """
    Singleton user-provided health context (V1 foundation).

    Optional contraception / pregnancy-fertility selections plus a free-text
    "anything else MenoMate should know" field. Every value is explicitly
    user-provided context: the backend stores it, returns it to the owning
    client, and never interprets it (no diagnosis, no inference, and no
    effect on prediction calculations).
    """
    __tablename__ = "health_contexts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    contraception_method: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    contraception_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pregnancy_context: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    health_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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

    user: Mapped["Profile"] = relationship("Profile", back_populates="health_context")


class HealthCondition(Base):
    """
    One user-reported health condition (context, NOT a MenoMate diagnosis).

    condition_code is a structured key from a small curated allowlist
    (validated in app/schemas/health_context.py); code "other" carries the
    user's own label in custom_label. Optional free-text note, active flag,
    and timestamps follow the existing domain-table conventions.
    """
    __tablename__ = "health_conditions"
    __table_args__ = (
        Index(
            "uq_health_condition_user_code",
            "user_id",
            "condition_code",
            unique=True,
            sqlite_where=text("custom_label IS NULL"),
            postgresql_where=text("custom_label IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    condition_code: Mapped[str] = mapped_column(String(64), nullable=False)
    custom_label: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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

    user: Mapped["Profile"] = relationship("Profile", back_populates="health_conditions")


class Medication(Base):
    """
    One user-provided medication or treatment (context only).

    The backend never provides medication advice and never infers
    conditions from medications.
    """
    __tablename__ = "medications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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

    user: Mapped["Profile"] = relationship("Profile", back_populates="medications")
