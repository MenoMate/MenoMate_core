from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class TrackingCompleteness(BaseModel):
    logged_days: int = 0
    window_days: int = 0
    coverage_ratio: float = 0.0
    complete_cycles: int = 0
    incomplete_cycles: int = 0
    pain_logged_days: int = 0
    missing_data_notes: List[str] = Field(default_factory=list)


class InsightRecord(BaseModel):
    insight_id: str
    insight_type: Literal[
        "frequent_symptom",
        "cycle_day_pattern",
        "pain_trend",
        "mood_pain_cooccurrence",
        "device_preference",
        "session_feedback_pattern",
    ]
    title: str
    explanation: str
    time_period: str
    supporting_counts: Dict[str, Any] = Field(default_factory=dict)
    data_completeness: Dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["low", "moderate", "high"]
    source_record_ids: List[str] = Field(default_factory=list)
    caveat: Optional[str] = None


class PatternAnalysisResult(BaseModel):
    insights: List[InsightRecord] = Field(default_factory=list)
    frequent_symptoms: List[Dict[str, Any]] = Field(default_factory=list)
    cycle_day_symptom_patterns: List[Dict[str, Any]] = Field(default_factory=list)
    pain_trend: Optional[Dict[str, Any]] = None
    mood_pain_patterns: List[Dict[str, Any]] = Field(default_factory=list)
    device_preference_summary: Optional[Dict[str, Any]] = None
    tracking_completeness: TrackingCompleteness = Field(default_factory=TrackingCompleteness)
    insufficient_data_reasons: List[str] = Field(default_factory=list)
