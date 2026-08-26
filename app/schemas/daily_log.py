import uuid
from datetime import date
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class FlowIntensityEnum(str, Enum):
    spotting = "spotting"
    light = "light"
    medium = "medium"
    heavy = "heavy"
    none = "none"


class MoodEnum(str, Enum):
    calm = "calm"
    anxious = "anxious"
    irritable = "irritable"
    fatigued = "fatigued"
    sad = "sad"


class DailyLogCreate(BaseModel):
    log_date: Optional[date] = Field(default=None, description="Date for the log. Defaults to current date.")
    cramp_severity: int = Field(..., ge=0, le=10, description="Pain score from 0 (none) to 10 (unbearable)")
    flow_intensity: FlowIntensityEnum = Field(default=FlowIntensityEnum.none)
    mood: MoodEnum = Field(default=MoodEnum.calm)
    symptoms: List[str] = Field(default_factory=list, description="List of symptoms e.g. headache, bloating, nausea")
    notes: Optional[str] = Field(default=None, description="Optional personal notes")


class DailyLogResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    log_date: date
    cramp_severity: int
    flow_intensity: str
    mood: str
    symptoms: List[str]
    notes: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
