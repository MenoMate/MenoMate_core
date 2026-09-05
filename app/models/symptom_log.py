from typing import TYPE_CHECKING
from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.daily_log import DailyLog


class SymptomLog(Base):
    """
    Child symptom record of a daily log.
    symptom_type: semantic identifier (e.g. cramps, headache, nausea, back_pain, low_energy, bloating, etc.)
    severity: 0-10 intensity score
    """
    __tablename__ = "symptom_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    daily_log_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("daily_logs.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    symptom_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    daily_log: Mapped["DailyLog"] = relationship("DailyLog", back_populates="symptoms")
