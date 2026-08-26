import uuid
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class VibrationModeEnum(str, Enum):
    constant = "constant"
    wave = "wave"
    pulse = "pulse"
    off = "off"


class FeedbackTagEnum(str, Enum):
    too_hot = "too_hot"
    just_right = "just_right"
    insufficient_relief = "insufficient_relief"


class TherapyRecommendationRequest(BaseModel):
    cramp_severity: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Optional override. If not provided, the active daily log's cramp severity is used.",
    )


class TherapyRecommendationResponse(BaseModel):
    cramp_severity: int
    target_temp_celsius: float
    vibration_mode: VibrationModeEnum
    vibration_intensity: int = Field(..., ge=0, le=100)
    duration_minutes: int
    reasoning: str
    applied_sensitivity_index: float


class TherapySessionCreate(BaseModel):
    target_temp_celsius: float = Field(..., ge=0.0, le=45.0, description="Target temperature in Celsius (max 45.0°C)")
    vibration_mode: VibrationModeEnum = Field(default=VibrationModeEnum.pulse)
    vibration_intensity: int = Field(..., ge=0, le=100)
    duration_minutes: int = Field(default=20, ge=1, le=120)
    pre_cramp_score: int = Field(..., ge=1, le=10)
    post_relief_score: Optional[int] = Field(default=None, ge=1, le=10)
    feedback_tag: Optional[FeedbackTagEnum] = None
    timestamp: Optional[datetime] = None


class TherapySessionFeedbackUpdate(BaseModel):
    post_relief_score: Optional[int] = Field(default=None, ge=1, le=10)
    feedback_tag: FeedbackTagEnum = Field(..., description="too_hot, just_right, or insufficient_relief")


class TherapySessionResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    timestamp: datetime
    target_temp_celsius: float
    vibration_mode: str
    vibration_intensity: int
    duration_minutes: int
    pre_cramp_score: int
    post_relief_score: Optional[int] = None
    feedback_tag: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
