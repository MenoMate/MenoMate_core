import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ProfileBase(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    usual_cycle_days: Optional[int] = Field(default=None, ge=20, le=45, description="Usual cycle days or null if unsure")
    usual_period_days: Optional[int] = Field(default=None, ge=1, le=12, description="Usual period days or null if unsure")
    theme: str = Field(default="system", max_length=32)
    units: str = Field(default="metric", max_length=32)
    sensitivity_index: float = Field(default=1.0, ge=0.5, le=1.5)


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    usual_cycle_days: Optional[int] = Field(default=None, ge=20, le=45)
    usual_period_days: Optional[int] = Field(default=None, ge=1, le=12)
    theme: Optional[str] = Field(default=None, max_length=32)
    units: Optional[str] = Field(default=None, max_length=32)
    sensitivity_index: Optional[float] = Field(default=None, ge=0.5, le=1.5)


class ProfileResponse(ProfileBase):
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
