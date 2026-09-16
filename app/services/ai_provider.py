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
    "Voice and Tone:\n"
    "Use warm, supportive, person-centered language addressed directly to the user (e.g. \"I'd suggest...\", \"Based on what you've shared...\", \"Based on your cycle...\"). "
    "Do NOT use generic population phrases like \"many users start with...\" or \"many people find...\".\n\n"
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
    "Authoritative facts (immutable):\n"
    "The user payload may contain a \"facts\" object with verified MenoMate values (cycle day, phase, "
    "logged pain, prediction details). Treat every value in \"facts\" as fixed: repeat values exactly "
    "when relevant and never alter numbers or dates. For missing (null) entries, describe the absence "
    "plainly instead of inventing a value. Every number or date in your reply MUST come from \"facts\".\n\n"
    "Follow-up:\n"
    "You may include at most one brief follow-up question as \"followup\" (or null when the answer is "
    "complete). A follow-up must be a single question that resolves ambiguity, personalizes the next "
    "answer, or enables a useful action. Never use filler closers such as \"Would you like to know more?\" "
    "or \"Anything else?\".\n\n"
    "Output Format:\n"
    "You must strictly output a valid JSON object matching this schema:\n"
    "{\n"
    '  "response": "Empathetic, practical, concise guidance",\n'
    '  "followup": "One targeted question" | null,\n'
    '  "therapy_profile": "GENTLE" | "MODERATE" | "STRONG" | null\n'
    "}"
)


class GroqExplainReply(BaseModel):
    """Structured model output (Step 3 contract).

    Routing intent is intentionally absent: topic routing is deterministic
    and the model must not reclassify. Extra keys (e.g. a legacy
    "intent") are tolerated and ignored.
    """

    response: str
    followup: Optional[str] = None
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
        facts: Optional[Dict[str, Any]] = None,
        topic: Optional[str] = None,
        recent_turns: Optional[list] = None,
    ) -> Dict[str, Any]:
        # Base (Mock) path ignores select-then-enhance extras: the
        # deterministic reply is built from context day/phase directly.
        reply = await self.generate_reply(context, user_message, intent)
        return {
            "response_text": reply,
            "followup": None,
            "therapy_profile": None,
            "is_ai_generated": self.is_real_ai,
        }


class MockAIProvider(BaseAIProvider):
    """
    Deterministic context-aware fallback (Step 4): renders the shared
    composer frames over the same facts as the enhanced path — same
    decisions and structure, plainer sentences. Never pretends to be an
    LLM (is_real_ai stays False) and never invents history.
    """
    is_real_ai: bool = False

    async def generate_reply(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
    ) -> str:
        from app.services.care_composer import compose_ai_reply, render_deterministic_reply
        from app.services.care_topics import classify_care_topic

        ctx = dict(context or {})
        topic = ctx.get("topic") or classify_care_topic(user_message, intent_hint=intent)
        composed = compose_ai_reply(topic, ctx, message=user_message)
        return render_deterministic_reply(composed)


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
            "followup": None,
            "therapy_profile": None,
            "is_ai_generated": False,
        }

    async def generate_care_response(
        self,
        context: Dict[str, Any],
        user_message: str,
        intent: Optional[str] = None,
        facts: Optional[Dict[str, Any]] = None,
        topic: Optional[str] = None,
        recent_turns: Optional[list] = None,
    ) -> Dict[str, Any]:
        if not self.api_key or not self.api_key.strip():
            logger.warning("Groq API key not configured. Falling back to deterministic guidance.")
            return await self._fallback(context, user_message, intent)

        prompt_payload = {
            "user_message": user_message,
            "intent": intent,
            "topic": topic,
            "facts": facts if facts is not None else {},
            "recent_turns": recent_turns or [],
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

            # Validate schema and allowed profile (model intent, if present,
            # is tolerated and ignored: routing is deterministic).
            parsed = GroqExplainReply.model_validate(raw_data)

            return {
                "response_text": parsed.response,
                "followup": parsed.followup,
                "therapy_profile": parsed.therapy_profile,
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
