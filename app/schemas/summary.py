from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.daily_log import DailyLogResponse


class CurrentSummaryResponse(BaseModel):
    has_data: bool
    current_cycle_day: Optional[int] = None
    phase: str = Field(..., description="Estimated phase: menstrual, follicular, ovulation, luteal")
    is_bleeding: bool
    latest_period_start: Optional[date] = None
    latest_period_end: Optional[date] = None
    predicted_next_period: Optional[date] = None
    days_until_next_period: Optional[int] = Field(
        default=None,
        description="Days until predicted next period start. Positive if upcoming, 0 if today, negative indicates days overdue if predicted date has passed without a new period.",
    )
    prediction_confidence: str = Field(..., description="high, moderate, low, or insufficient_data")
    average_cycle_length: Optional[int] = None
    average_period_length: Optional[int] = None
    today_log: Optional[DailyLogResponse] = None
    recent_pain_avg: Optional[float] = None
    frequent_symptoms: List[str] = []


class HistoryPeriodEntry(BaseModel):
    id: int
    period_start: date
    period_end: Optional[date] = None
    period_length_days: Optional[int] = None
    cycle_length_days: Optional[int] = None


class HistorySummaryResponse(BaseModel):
    total_periods_logged: int
    average_cycle_length: Optional[float] = None
    average_period_length: Optional[float] = None
    cycle_variability_std_dev: Optional[float] = None
    history: List[HistoryPeriodEntry] = []
    symptom_frequencies: Dict[str, int] = {}
