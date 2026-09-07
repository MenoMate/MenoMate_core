import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.core.config import settings

logger = logging.getLogger("menomate.ai_provider")

ALLOWED_THERAPY_PROFILES = {"GENTLE", "MODERATE", "STRONG"}

FORBIDDEN_HARDWARE_FIELDS = {
    "temperature",
    "target_temperature",
    "target_temp",
    "target_temp_c",
    "pwm",
    "vibration_percent",
    "vibration_intensity",
    "duration_minutes",
    "duration",
    "gpio",
    "ble_command",
    "motor_speed",
    "heater_power",
    "heater_temperature",
}

GROQ_CARE_SYSTEM_PROMPT = (
    "You are MenoMate Care, a focused menstrual-wellness assistant inside the MenoMate application.\n"
    "Your job is to help the user understand their menstrual-cycle-related data, symptoms, pain patterns, "
    "mood patterns, wellness habits, therapy history, and MenoMate features.\n\n"
    "Stay strictly within MenoMate's scope.\n"
    "You may:\n"
    "- explain menstrual-wellness concepts at a general level\n"
    "- summarize patterns from the user's provided data\n"
    "- help interpret logged symptoms\n"
    "- provide general self-care suggestions\n"
    "- discuss how the MenoMate wearable has been used\n"
    "- personalize recommendations using verified user history\n"
    "- recommend one of the backend-defined therapy profiles when appropriate\n"
    "- explain MenoMate features\n\n"
    "You are not a general-purpose assistant. For unrelated requests (such as general programming, sports, "
    "politics, general trivia, homework), set intent to 'out_of_scope', set therapy_profile to null, "
    "and politely state: \"I'm here to help with your menstrual wellness, cycle data, symptoms, and MenoMate features. I can't help with unrelated topics.\"\n\n"
    "Safety Rules:\n"
    "1. Never diagnose a medical condition or prescribe medication.\n"
    "2. Never claim certainty when the available data is insufficient.\n"
    "3. Never invent user history, symptoms, preferences, or previous therapy results. "
    "If context indicates insufficient or no history, state that clearly instead of assuming preferences.\n"
    "4. Never contradict deterministic safety or red-flag decisions supplied by the backend.\n"
    "5. Never create or modify raw hardware settings. You may recommend only a therapy profile from the "
    "backend-provided allowed list: [\"GENTLE\", \"MODERATE\", \"STRONG\"] or null.\n"
    "6. Never output temperature values, PWM values, GPIO instructions, BLE commands, motor commands, "
    "heater commands, arbitrary therapy duration, or actuator parameters. "
    "The backend is authoritative for safety and final therapy configuration.\n\n"
    "Output Format:\n"
    "You must strictly output a valid JSON object matching this schema:\n"
    "{\n"
    '  "response": "Empathetic, practical, concise guidance",\n'
    '  "intent": "care | pattern_summary | therapy_recommendation | feature_help | out_of_scope",\n'
    '  "therapy_profile": "GENTLE" | "MODERATE" | "STRONG" | null\n'
    "}"
)


class GroqCareStructuredReply(BaseModel):
    response: str
    intent: str = "care"
    therapy_profile: Optional[str] = None

    @field_validator("therapy_profile", mode="before")
    @classmethod
    def validate_therapy_profile(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().upper()
        if not s or s in ("NULL", "NONE"):
            return None
        if s in ALLOWED_THERAPY_PROFILES:
            return s
        raise ValueError(f"Unsupported therapy profile: {v}")


class BaseAIProvider(ABC):
    """
    Abstract interface for MenoMate Care AI providers.
    """
    is_real_ai: bool = False

    @abstractmethod
    async def generate_reply(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        pass

    async def generate_care_response(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        reply = await self.generate_reply(context, user_message, intent)
        return {
            "response_text": reply,
            "intent": intent or "care",
            "therapy_profile": None,
            "is_ai_generated": self.is_real_ai,
        }


class MockAIProvider(BaseAIProvider):
    """
    Mock AI Provider providing safe, empathetic, non-diagnostic guidance
    for development, testing, and offline environments.
    Strictly avoids clinical diagnoses or prescribing medication.
    """
    is_real_ai: bool = False

    async def generate_reply(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        cycle_day = context.get("cycle_day", "unknown")
        phase = context.get("phase", "current")
        msg_lower = user_message.lower()

        if "cramp" in msg_lower or "pain" in msg_lower or intent in ("pain_help", "therapy_recommendation"):
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


class GroqAIProvider(BaseAIProvider):
    """
    Production Groq AI Provider using AsyncGroq and configurable model (default openai/gpt-oss-120b).
    Strictly validates structured JSON responses and enforces hardware safety boundaries.
    """
    is_real_ai: bool = True

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[Any] = None,
    ):
        self.api_key = api_key or settings.GROQ_API_KEY
        self.model = model or getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b")
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from groq import AsyncGroq
        return AsyncGroq(api_key=self.api_key)

    async def _fallback(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str],
    ) -> Dict[str, Any]:
        mock = MockAIProvider()
        reply = await mock.generate_reply(context, user_message, intent)
        return {
            "response_text": reply,
            "intent": intent or "care",
            "therapy_profile": None,
            "is_ai_generated": False,
        }

    async def generate_care_response(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.api_key or not self.api_key.strip():
            logger.warning("Groq API key not configured. Falling back to deterministic guidance.")
            return await self._fallback(context, user_message, intent)

        prompt_payload = {
            "user_message": user_message,
            "intent": intent,
            "context": context,
        }

        try:
            client = self._get_client()
            response = await client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": GROQ_CARE_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(prompt_payload, default=str)},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=600,
            )
            content = response.choices[0].message.content
            if not content:
                logger.warning("Empty response from Groq. Falling back.")
                return await self._fallback(context, user_message, intent)

            raw_data = json.loads(content)
            if not isinstance(raw_data, dict):
                logger.warning("Groq response was not a JSON object. Falling back.")
                return await self._fallback(context, user_message, intent)

            # Defensive validation: Reject any raw hardware control fields
            forbidden_keys = [
                k for k in raw_data.keys()
                if k.lower() in FORBIDDEN_HARDWARE_FIELDS and raw_data[k] is not None
            ]
            if forbidden_keys:
                logger.warning(
                    f"Groq response contained forbidden hardware fields: {forbidden_keys}. Rejecting output."
                )
                return await self._fallback(context, user_message, intent)

            # Validate schema and allowed profile
            parsed = GroqCareStructuredReply.model_validate(raw_data)

            # Enforce out-of-scope invariant: therapy profile must be None
            therapy_prof = parsed.therapy_profile
            if parsed.intent == "out_of_scope":
                therapy_prof = None

            return {
                "response_text": parsed.response,
                "intent": parsed.intent,
                "therapy_profile": therapy_prof,
                "is_ai_generated": True,
            }
        except Exception as e:
            logger.warning(f"Groq generation failed ({type(e).__name__}: {e}). Falling back safely.")
            return await self._fallback(context, user_message, intent)

    async def generate_reply(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        care_res = await self.generate_care_response(context, user_message, intent)
        return care_res["response_text"]


_provider_override: Optional[BaseAIProvider] = None


def set_ai_provider(provider: Optional[BaseAIProvider]) -> None:
    """
    Override the active AI provider (used for testing or runtime provider swap).
    """
    global _provider_override
    _provider_override = provider


def get_ai_provider() -> BaseAIProvider:
    """
    Pluggable AI provider factory.
    Returns overridden provider if set, else GroqAIProvider if GROQ_API_KEY is configured,
    else falls back to MockAIProvider.
    """
    global _provider_override
    if _provider_override is not None:
        return _provider_override

    if settings.GROQ_API_KEY and settings.GROQ_API_KEY.strip():
        return GroqAIProvider(
            api_key=settings.GROQ_API_KEY,
            model=getattr(settings, "GROQ_MODEL", "openai/gpt-oss-120b"),
        )

    return MockAIProvider()
