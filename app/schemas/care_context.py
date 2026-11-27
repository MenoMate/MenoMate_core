from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.insights import InsightRecord, TrackingCompleteness


class CycleHistorySummary(BaseModel):
    has_data: bool = False
    current_cycle_day: Optional[int] = None
    phase: str = "unknown"
    is_bleeding: bool = False
    predicted_next_period: Optional[str] = None
    days_until_next_period: Optional[int] = None
    prediction_confidence: Optional[str] = None
    prediction_source: Optional[str] = None
    recent_cycle_lengths: List[int] = Field(default_factory=list)
    usual_cycle_length: Optional[int] = None
    completed_cycle_count: int = 0
    incomplete_cycle_count: int = 0


class DailyLogSnapshot(BaseModel):
    id: int
    date: str
    cycle_day: Optional[int] = None
    pain: Optional[int] = None
    mood: Optional[str] = None
    moods: List[str] = Field(default_factory=list)
    flow: Optional[str] = None
    discharge: Optional[str] = None
    symptoms: List[Dict[str, Any]] = Field(default_factory=list)


class DeviceSessionSummary(BaseModel):
    id: int
    started_at: str
    mode: str
    profile: str
    requested_heat_level: Optional[int] = None
    requested_duration_minutes: Optional[int] = None
    vibration_mode: Optional[str] = None
    command_status: Optional[str] = None
    ack_status: Optional[str] = None
    session_status: Optional[str] = None
    pain_before: Optional[int] = None
    pain_after: Optional[int] = None
    feedback: Optional[str] = None
    comfort_rating: Optional[str] = None
    noticed_improvement: Optional[bool] = None


class MemorySnapshot(BaseModel):
    id: int
    category: str
    key: str
    value: str
    source: str


class PersonalCareContext(BaseModel):
    """Typed, compact, user-isolated context object for MenoMate Care."""

    intent: str
    topic: Optional[str] = None
    cycle: CycleHistorySummary = Field(default_factory=CycleHistorySummary)
    recent_logs: List[DailyLogSnapshot] = Field(default_factory=list)
    frequent_symptoms: List[str] = Field(default_factory=list)
    recent_pain_avg: Optional[float] = None
    insights: List[InsightRecord] = Field(default_factory=list)
    pain_trend: Optional[Dict[str, Any]] = None
    memories: List[MemorySnapshot] = Field(default_factory=list)
    health_conditions: List[str] = Field(default_factory=list)
    medications: List[str] = Field(default_factory=list)
    devices_linked: int = 0
    recent_therapy_sessions: List[DeviceSessionSummary] = Field(default_factory=list)
    device_preference_summary: Optional[Dict[str, Any]] = None
    recent_pattern: Dict[str, Any] = Field(default_factory=dict)
    recommendation: Optional[Dict[str, Any]] = None
    sensitivity_index: float = 1.0
    tracking_completeness: TrackingCompleteness = Field(default_factory=TrackingCompleteness)
    has_history: bool = False
    history_note: str = ""
