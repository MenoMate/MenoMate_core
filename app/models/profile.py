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
    from app.models.therapy_session import TherapySession
    from app.models.chat import ChatConversation


class Profile(Base):
    __tablename__ = "profiles"

    # User ID matches Supabase auth.users.id
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    usual_cycle_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usual_period_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    theme: Mapped[str] = mapped_column(String(32), default="system", nullable=False)
    units: Mapped[str] = mapped_column(String(32), default="metric", nullable=False)
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
    conversations: Mapped[List["ChatConversation"]] = relationship(
        "ChatConversation", back_populates="user", cascade="all, delete-orphan"
    )
