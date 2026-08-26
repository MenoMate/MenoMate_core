import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


class TherapySession(Base):
    __tablename__ = "therapy_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    target_temp_celsius: Mapped[float] = mapped_column(Float, nullable=False)
    vibration_mode: Mapped[str] = mapped_column(String(32), default="pulse", nullable=False)
    vibration_intensity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    pre_cramp_score: Mapped[int] = mapped_column(Integer, nullable=False)
    post_relief_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feedback_tag: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    user: Mapped["Profile"] = relationship("Profile", back_populates="therapy_sessions")
