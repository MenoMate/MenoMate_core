from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class CareIntentEnum(str, Enum):
    cycle_insight = "cycle_insight"
    symptom_insight = "symptom_insight"
    pain_help = "pain_help"
    wellness_help = "wellness_help"
    device_help = "device_help"
    other = "other"


class CareInteractionRequest(BaseModel):
    intent: CareIntentEnum = Field(
        default=CareIntentEnum.wellness_help,
        description="Canonical intent type: cycle_insight, symptom_insight, pain_help, wellness_help, device_help, or other",
    )
    user_message: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional user inquiry or message",
    )


class CareInteractionResponse(BaseModel):
    intent: CareIntentEnum
    response_text: str
    is_ai_generated: bool
    suggested_actions: List[str] = []
    disclaimer: str
