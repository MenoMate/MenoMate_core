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
    Strictly avoids clinical diagnoses or prescribing medication.
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
                f"Around day {cycle_day} ({phase} phase), cramping can feel uncomfortable. "
                "Some people find that gentle warmth (like a warm compress or our wearable's safe thermal setting), "
                "light movement, or resting in a comfortable position can offer comfort. "
                "If pain feels unusually sharp or severe, please consider speaking with a healthcare professional."
            )
        elif "tired" in msg_lower or "fatigue" in msg_lower:
            return (
                f"Feeling low energy around day {cycle_day} ({phase} phase) is something many people experience. "
                "Light stretching, staying well-hydrated, and taking extra time for rest may help you feel more restored. "
                "If fatigue feels persistent or overwhelming, consider speaking with a healthcare provider."
            )
        elif "nausea" in msg_lower:
            return (
                f"Mild nausea can sometimes occur around this time. Small, frequent sips of water or herbal tea "
                "and plain snacks may feel soothing. If nausea persists or is severe, consult a medical provider."
            )
        elif "mood" in msg_lower:
            return (
                f"Mood shifts can happen during different parts of your cycle. "
                "Taking quiet moments for yourself, gentle walks, and prioritizing sleep may help you feel more grounded. "
                "If mood changes feel unmanageable, a professional can offer personalized support."
            )
        else:
            return (
                f"Thank you for checking in. In your {phase} phase (cycle day {cycle_day}), tracking your symptoms "
                "helps build a clearer picture of your personal rhythms. If you ever have health concerns, "
                "a healthcare provider is best suited to guide you. How else can I support your comfort today?"
            )


# Default provider instance
def get_ai_provider() -> BaseAIProvider:
    # Pluggable: can read env config if an external provider is configured
    return MockAIProvider()
