import uuid
from datetime import date, datetime, timedelta
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class FlowEnum(str, Enum):
    none = "none"
    spotting = "spotting"
    light = "light"
    medium = "medium"
    heavy = "heavy"


class MoodEnum(str, Enum):
    happy = "happy"
    calm = "calm"
    neutral = "neutral"
    sad = "sad"
    irritable = "irritable"
    anxious = "anxious"
    tired = "tired"


class DischargeEnum(str, Enum):
    none = "none"
    light = "light"
    moderate = "moderate"
    heavy = "heavy"


SUPPORTED_SYMPTOMS = [
    {"id": "cramps", "display_name": "Cramps", "category": "pain"},
    {"id": "headache", "display_name": "Headache", "category": "pain"},
    {"id": "back_pain", "display_name": "Lower Back Pain", "category": "pain"},
    {"id": "nausea", "display_name": "Nausea", "category": "digestive"},
    {"id": "bloating", "display_name": "Bloating", "category": "digestive"},
    {"id": "low_energy", "display_name": "Low Energy / Fatigue", "category": "energy"},
    {"id": "breast_tenderness", "display_name": "Breast Tenderness", "category": "physical"},
    {"id": "acne", "display_name": "Acne / Skin Breakouts", "category": "skin"},
    {"id": "sleep_difficulty", "display_name": "Sleep Difficulty", "category": "sleep"},
    {"id": "appetite_change", "display_name": "Appetite Changes", "category": "diet"},
    {"id": "dizziness", "display_name": "Dizziness / Lightheadedness", "category": "general"},
]

SUPPORTED_SYMPTOM_IDS = {s["id"] for s in SUPPORTED_SYMPTOMS}


class SymptomItem(BaseModel):
    symptom_type: str = Field(..., max_length=64)
    severity: int = Field(default=0, ge=0, le=10, description="Severity score 0 to 10")

    @field_validator("symptom_type")
    @classmethod
    def validate_symptom_type(cls, v: str) -> str:
        clean_v = v.strip().lower()
        if clean_v not in SUPPORTED_SYMPTOM_IDS:
            raise ValueError(
                f"Unsupported symptom_type '{v}'. Supported: {sorted(SUPPORTED_SYMPTOM_IDS)}"
            )
        return clean_v

    model_config = ConfigDict(from_attributes=True)


class DailyLogCreate(BaseModel):
    log_date: Optional[date] = Field(default=None, description="Date for this entry; defaults to today")
    pain: int = Field(default=0, ge=0, le=10, description="Overall pain/cramp level 0 to 10")
    mood: Optional[MoodEnum] = None
    discharge: Optional[DischargeEnum] = None
    flow: Optional[FlowEnum] = None
    symptoms: List[SymptomItem] = Field(default_factory=list, description="Child symptom records")
    notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("log_date")
    @classmethod
    def validate_log_date(cls, v: Optional[date]) -> Optional[date]:
        if v and v > date.today() + timedelta(days=1):
            raise ValueError("log_date cannot be in the future")
        return v


class DailyLogUpdate(BaseModel):
    pain: Optional[int] = Field(default=None, ge=0, le=10)
    mood: Optional[MoodEnum] = None
    discharge: Optional[DischargeEnum] = None
    flow: Optional[FlowEnum] = None
    symptoms: Optional[List[SymptomItem]] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


class DailyLogResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    log_date: date
    pain: int
    mood: Optional[str] = None
    discharge: Optional[str] = None
    flow: Optional[str] = None
    notes: Optional[str] = None
    symptoms: List[SymptomItem] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SymptomMeta(BaseModel):
    id: str
    display_name: str
    category: str
