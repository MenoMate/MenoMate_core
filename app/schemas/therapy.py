import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


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
    feedback: Optional[str] = Field(default=None, max_length=64)


class TherapySessionUpdate(BaseModel):
    ended_at: Optional[datetime] = None
    pain_after: Optional[int] = Field(default=None, ge=0, le=10)
    feedback: Optional[str] = Field(default=None, max_length=64)


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
