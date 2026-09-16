from datetime import date
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.cycle import validate_period_dates
from app.schemas.profile import ProfileResponse


class OnboardingRequest(BaseModel):
    # Completion contract (§2.1): onboarding is complete only when the
    # profile carries a non-blank name AND at least one cycle exists.
    # The backend enforces the name half here (stripped, non-blank);
    # the route enforces the cycle half by always creating the first
    # period and by rejecting re-onboarding once complete. The Flutter
    # router uses the same name-non-blank definition — never weaken one
    # side to compensate for the other.
    name: str = Field(..., min_length=1, max_length=128, description="Display name (required, non-blank)")
    last_period_start: date = Field(..., description="First day of last bleeding period")
    last_period_end: Optional[date] = Field(default=None, description="Last day of bleeding, or null if ongoing")
    usual_cycle_days: Optional[int] = Field(
        default=None, ge=20, le=45, description="Usual cycle days or null for 'I'm not sure'"
    )
    usual_period_days: Optional[int] = Field(
        default=None, ge=1, le=12, description="Usual period days or null for 'I'm not sure'"
    )
    timezone: Optional[str] = Field(
        default=None, max_length=64, description="Device IANA timezone identifier, e.g. Asia/Kolkata"
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

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
