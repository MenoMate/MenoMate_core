import uuid
from datetime import date
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import Date, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


class DailyLog(Base):
    __tablename__ = "daily_logs"
    __table_args__ = (
        UniqueConstraint("user_id", "log_date", name="uq_user_log_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    log_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    cramp_severity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flow_intensity: Mapped[str] = mapped_column(String(32), default="none", nullable=False)
    mood: Mapped[str] = mapped_column(String(32), default="calm", nullable=False)
    symptoms: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["Profile"] = relationship("Profile", back_populates="daily_logs")
