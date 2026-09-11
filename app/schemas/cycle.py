import uuid
from datetime import date, datetime, timedelta
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


def validate_period_dates(period_start: date, period_end: Optional[date] = None) -> None:
    # Prevent future period start dates (allow +1 day for timezone variance)
    tomorrow = date.today() + timedelta(days=1)
    if period_start > tomorrow:
        raise ValueError("period_start cannot be in the future")

    if period_end is not None:
        if period_end < period_start:
            raise ValueError("period_end cannot be prior to period_start")
        if (period_end - period_start).days > 30:
            raise ValueError("period duration cannot exceed 30 days")


class CycleCreate(BaseModel):
    period_start: date = Field(..., description="First day of period bleeding")
    period_end: Optional[date] = Field(default=None, description="Last day of period bleeding, or null if ongoing")

    @model_validator(mode="after")
    def validate_dates(self) -> "CycleCreate":
        validate_period_dates(self.period_start, self.period_end)
        return self


class CycleUpdate(BaseModel):
    period_start: Optional[date] = None
    period_end: Optional[date] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "CycleUpdate":
        tomorrow = date.today() + timedelta(days=1)
        if self.period_start and self.period_start > tomorrow:
            raise ValueError("period_start cannot be in the future")

        if self.period_start and self.period_end:
            if self.period_end < self.period_start:
                raise ValueError("period_end cannot be prior to period_start")
            if (self.period_end - self.period_start).days > 30:
                raise ValueError("period duration cannot exceed 30 days")
        return self


class CycleResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    period_start: date
    period_end: Optional[date] = None
    period_length_days: Optional[int] = Field(default=None, description="Computed bleeding duration in days")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CurrentCycleResponse(BaseModel):
    has_data: bool
    current_cycle_day: Optional[int] = None
    phase: str
    is_bleeding: bool
    is_ongoing: bool = False
    active_cycle_id: Optional[int] = None
    latest_period_start: Optional[date] = None
    latest_period_end: Optional[date] = None
    predicted_cycle_length: Optional[int] = None
    predicted_next_period: Optional[date] = None
    days_until_next_period: Optional[int] = Field(
        default=None,
        description="Days until predicted next period. 0 if expected today or already passed. Null if insufficient data. Never negative.",
    )
    prediction_status: Optional[str] = Field(
        default=None,
        description="Neutral prediction state: upcoming, today, awaiting_next_start. Null if insufficient data.",
    )
    prediction_confidence: str
    prediction_source: Optional[str] = None
    average_cycle_length: Optional[int] = None
    average_period_length: Optional[int] = None
