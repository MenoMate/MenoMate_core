from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class TherapyFeedbackEnum(str, Enum):
    insufficient_relief = "insufficient_relief"
    too_hot = "too_hot"
    just_right = "just_right"


class TherapyRecommendationRequest(BaseModel):
    pain_score: Optional[int] = Field(
        default=None, ge=0, le=10, description="Optional override; defaults to today's logged pain"
    )


class TherapyRecommendationResponse(BaseModel):
    pain_score: int
    target_temperature_c: float = Field(..., le=44.0, description="Strict 44.0°C policy ceiling")
    vibration_mode: str
    vibration_intensity: int = Field(..., ge=0, le=100)
    duration_minutes: int
    reasoning: str
    applied_sensitivity_index: float


class TherapySessionCreate(BaseModel):
    device_id: Optional[uuid.UUID] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    mode: str = Field(default="standard", max_length=32)
    target_temperature_c: Optional[float] = Field(default=None, le=44.0)
    vibration_intensity: Optional[int] = Field(default=None, ge=0, le=100)
    vibration_mode: Optional[str] = Field(default="pulse", max_length=32)
    pain_before: Optional[int] = Field(default=None, ge=0, le=10)
    pain_after: Optional[int] = Field(default=None, ge=0, le=10)
    feedback: Optional[TherapyFeedbackEnum] = None

    @model_validator(mode="after")
    def validate_session_dates(self) -> "TherapySessionCreate":
        if self.started_at and self.ended_at:
            s = self.started_at if self.started_at.tzinfo is not None else self.started_at.replace(tzinfo=timezone.utc)
            e = self.ended_at if self.ended_at.tzinfo is not None else self.ended_at.replace(tzinfo=timezone.utc)
            if e < s:
                raise ValueError("ended_at cannot be prior to started_at")
        return self


class TherapySessionUpdate(BaseModel):
    ended_at: Optional[datetime] = None
    pain_after: Optional[int] = Field(default=None, ge=0, le=10)
    feedback: Optional[TherapyFeedbackEnum] = None


class TherapySessionResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    device_id: Optional[uuid.UUID] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    mode: str
    target_temperature_c: Optional[float] = None
    vibration_intensity: Optional[int] = None
    vibration_mode: Optional[str] = None
    pain_before: Optional[int] = None
    pain_after: Optional[int] = None
    feedback: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
