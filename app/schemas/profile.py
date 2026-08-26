import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ProfileBase(BaseModel):
    cycle_length_avg: int = Field(default=28, ge=20, le=45, description="Average cycle length in days")
    period_length_avg: int = Field(default=5, ge=1, le=12, description="Average period length in days")
    sensitivity_index: float = Field(default=1.0, ge=0.5, le=1.5, description="Thermal sensitivity calibration multiplier")


class ProfileCreate(ProfileBase):
    pass


class ProfileSyncRequest(BaseModel):
    cycle_length_avg: Optional[int] = Field(default=28, ge=20, le=45)
    period_length_avg: Optional[int] = Field(default=5, ge=1, le=12)
    sensitivity_index: Optional[float] = Field(default=1.0, ge=0.5, le=1.5)


class ProfileUpdate(BaseModel):
    cycle_length_avg: Optional[int] = Field(default=None, ge=20, le=45)
    period_length_avg: Optional[int] = Field(default=None, ge=1, le=12)
    sensitivity_index: Optional[float] = Field(default=None, ge=0.5, le=1.5)


class ProfileResponse(ProfileBase):
    id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
