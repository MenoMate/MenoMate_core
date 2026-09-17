from enum import Enum
import uuid
from datetime import date, datetime
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
    timezone: Optional[str] = Field(default=None, max_length=64, description="IANA timezone identifier, e.g. Asia/Kolkata")
    birth_year: Optional[int] = Field(default=None, description="Birth year; always paired with birth_month (month/year precision only, no birth day)")
    birth_month: Optional[int] = Field(default=None, description="Birth month 1-12; always paired with birth_year")


def validate_birth_pair(birth_year: Optional[int], birth_month: Optional[int]) -> None:
    """
    Enforce month/year-precision DOB semantics: both parts set or both
    cleared, plausible year (never in the future), month 1-12. The server
    never infers age from incomplete information.
    """
    if (birth_year is None) != (birth_month is None):
        raise ValueError("birth_year and birth_month must be provided together or both cleared")
    if birth_year is not None and birth_year > date.today().year:
        raise ValueError("birth_year cannot be in the future")
    if birth_year is not None and birth_year < 1900:
        raise ValueError("birth_year is implausibly early")
    if birth_month is not None and not 1 <= birth_month <= 12:
        raise ValueError("birth_month must be between 1 and 12")


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    usual_cycle_days: Optional[int] = Field(default=None, ge=20, le=45)
    usual_period_days: Optional[int] = Field(default=None, ge=1, le=12)
    theme: Optional[ThemeEnum] = None
    units: Optional[UnitsEnum] = None
    timezone: Optional[str] = Field(default=None, max_length=64)
    birth_year: Optional[int] = Field(default=None, ge=1900)
    birth_month: Optional[int] = Field(default=None, ge=1, le=12)


class ProfileResponse(ProfileBase):
    user_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
