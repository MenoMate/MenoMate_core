from enum import Enum
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class ThemeEnum(str, Enum):
    system = "system"
    light = "light"
    dark = "dark"


class UnitsEnum(str, Enum):
    metric = "metric"
    imperial = "imperial"


class ProfileBase(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    usual_cycle_days: Optional[int] = Field(default=None, ge=20, le=45, description="Usual cycle days or null if unsure")
    usual_period_days: Optional[int] = Field(default=None, ge=1, le=12, description="Usual period days or null if unsure")
    theme: ThemeEnum = Field(default=ThemeEnum.system)
    units: UnitsEnum = Field(default=UnitsEnum.metric)
    sensitivity_index: float = Field(default=1.0, ge=0.5, le=1.5)


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    usual_cycle_days: Optional[int] = Field(default=None, ge=20, le=45)
    usual_period_days: Optional[int] = Field(default=None, ge=1, le=12)
    theme: Optional[ThemeEnum] = None
    units: Optional[UnitsEnum] = None


class ProfileResponse(ProfileBase):
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
