import uuid
from datetime import date
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CycleStartRequest(BaseModel):
    start_date: Optional[date] = Field(default=None, description="Start date of the new cycle. Defaults to today.")


class CycleEndRequest(BaseModel):
    end_date: Optional[date] = Field(default=None, description="End date of the cycle. Defaults to today.")


class CycleResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    start_date: date
    end_date: Optional[date] = None
    predicted_ovulation: Optional[date] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class CurrentCycleStatusResponse(BaseModel):
    active_cycle: Optional[CycleResponse] = None
    current_cycle_day: Optional[int] = Field(None, description="Day of the current cycle (1-indexed)")
    predicted_ovulation: Optional[date] = Field(None, description="Estimated ovulation date")
    predicted_next_period: Optional[date] = Field(None, description="Estimated next period start date")
    days_until_next_period: Optional[int] = Field(None, description="Days remaining until next estimated period")
    cycle_length_avg: int = Field(28, description="User's rolling average cycle length")
