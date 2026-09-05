from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseAIProvider(ABC):
    """
    Abstract interface for MenoMate Care AI providers.
    """
    @abstractmethod
    async def generate_reply(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        pass


class MockAIProvider(BaseAIProvider):
    """
    Mock AI Provider providing safe, empathetic, non-diagnostic guidance
    for development, testing, and offline environments.
    """
    async def generate_reply(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        cycle_day = context.get("cycle_day", "unknown")
        phase = context.get("phase", "current")
        msg_lower = user_message.lower()

        if "cramp" in msg_lower or "pain" in msg_lower or intent == "pain_help":
            return (
                f"I hear you. During day {cycle_day} ({phase} phase), cramping can be particularly challenging. "
                "Gentle heat therapy (like a warm compress or our wearable's safe pulse setting), staying hydrated, "
                "and restful breathing can help soothe the abdominal muscles. If your pain feels unusually sharp or severe, "
                "please check in with a healthcare professional."
            )
        elif "tired" in msg_lower or "fatigue" in msg_lower:
            return (
                f"Feeling low energy around day {cycle_day} ({phase} phase) is very common as hormonal shifts alter your metabolic rhythm. "
                "Prioritize magnesium-rich snacks, gentle stretching, and an early night. Listen to your body and rest without guilt."
            )
        elif "nausea" in msg_lower:
            return (
                f"Mild nausea can occasionally accompany hormonal changes in the {phase} phase. "
                "Small, frequent sips of ginger or peppermint tea and bland snacks like crackers can provide relief. "
                "If nausea is persistent or accompanied by fever, consult a medical provider."
            )
        elif "mood" in msg_lower:
            return (
                f"Experiencing mood fluctuations during the {phase} phase is completely natural. "
                "Allow yourself space to unwind, step outside for fresh air, and engage in calming routines."
            )
        else:
            return (
                f"Thank you for sharing. In your {phase} phase (cycle day {cycle_day}), keeping track of your bodily changes "
                "helps build a clearer picture of your wellness rhythms. How else can I support your comfort today?"
            )


# Default provider instance
def get_ai_provider() -> BaseAIProvider:
    # Pluggable: can read env config if an external provider is configured
    return MockAIProvider()
