from enum import Enum
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class CareIntentEnum(str, Enum):
    cycle_insight = "cycle_insight"
    symptom_insight = "symptom_insight"
    pain_help = "pain_help"
    wellness_help = "wellness_help"
    device_help = "device_help"
    pattern_summary = "pattern_summary"
    therapy_recommendation = "therapy_recommendation"
    feature_help = "feature_help"
    general_inquiry = "general_inquiry"
    other = "other"


class CareRecentTurn(BaseModel):
    """One retained turn of the active Care session (Step 1).

    Transient by contract: accepted on the request, forwarded to the AI
    provider as conversation context, never persisted anywhere.
    """

    role: Literal["user", "care"] = Field(description="Turn speaker")
    text: str = Field(..., max_length=500, description="Turn text (client-truncated)")
    topic: Optional[str] = Field(
        default=None, max_length=64, description="Topic recorded for the turn, if known"
    )


class CareInteractionRequest(BaseModel):
    intent: CareIntentEnum = Field(
        default=CareIntentEnum.wellness_help,
        description="Canonical intent type: cycle_insight, symptom_insight, pain_help, wellness_help, device_help, pattern_summary, therapy_recommendation, feature_help, or other",
    )
    user_message: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional user inquiry or message",
    )
    recent_turns: List[CareRecentTurn] = Field(
        default_factory=list,
        description="Transient active-session turns (most recent last). Never stored; forwarded to the provider as conversation context only.",
    )


class CareAction(BaseModel):
    """One semantic UI action: stable id for routing, label for display."""

    id: str = Field(description="Semantic action id, e.g. open_logger")
    label: str = Field(description="User-facing chip label")


class CareInteractionResponse(BaseModel):
    intent: CareIntentEnum
    response_text: str
    is_ai_generated: bool
    tier: Literal["info", "advisory", "urgent"] = Field(
        default="info",
        description="Deterministic response tier: info, advisory, or urgent. The UI renders urgent/advisory distinctly.",
    )
    actions: List[CareAction] = Field(
        default_factory=list,
        description="Deterministic semantic actions ({id, label}). The model never chooses actions.",
    )
    disclaimer: str
    therapy_profile: Optional[str] = None
