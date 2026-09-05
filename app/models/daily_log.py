import uuid
from datetime import date, datetime, timezone
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.profile import Profile
    from app.models.symptom_log import SymptomLog


class DailyLog(Base):
    """
    One daily log per user per calendar day.
    Captures pain, mood, discharge, flow, notes, and child symptoms.
    """
    __tablename__ = "daily_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_user_log_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    log_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    pain: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mood: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    discharge: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    flow: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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

    user: Mapped["Profile"] = relationship("Profile", back_populates="daily_logs")
    symptoms: Mapped[List["SymptomLog"]] = relationship(
        "SymptomLog", back_populates="daily_log", cascade="all, delete-orphan", lazy="selectin"
    )
