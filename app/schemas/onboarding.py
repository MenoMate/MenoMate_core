from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, model_validator

from app.schemas.cycle import validate_period_dates
from app.schemas.profile import ProfileResponse


class OnboardingRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    last_period_start: date = Field(..., description="First day of last bleeding period")
    last_period_end: Optional[date] = Field(default=None, description="Last day of bleeding, or null if ongoing")
    usual_cycle_days: Optional[int] = Field(
        default=None, ge=20, le=45, description="Usual cycle days or null for 'I\\'m not sure'"
    )
    usual_period_days: Optional[int] = Field(
        default=None, ge=1, le=12, description="Usual period days or null for 'I\\'m not sure'"
    )

    @model_validator(mode="after")
    def validate_dates(self) -> "OnboardingRequest":
        validate_period_dates(self.last_period_start, self.last_period_end)
        return self


class OnboardingResponse(BaseModel):
    message: str
    profile: ProfileResponse
    period_id: int
    period_start: date
    period_end: Optional[date] = None
