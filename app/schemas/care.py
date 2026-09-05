from typing import List, Optional
from pydantic import BaseModel, Field


class CareInteractionRequest(BaseModel):
    intent: str = Field(
        default="wellness_help",
        description="Intent type: cycle_insight, symptom_insight, pain_help, wellness_help, device_help, or other",
    )
    user_message: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional user inquiry or message",
    )


class CareInteractionResponse(BaseModel):
    intent: str
    response_text: str
    is_ai_generated: bool
    suggested_actions: List[str] = []
    disclaimer: str
