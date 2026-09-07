import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.therapy_session import TherapySession
from app.services.ai_context import build_care_context
from app.services.ai_provider import (
    GroqAIProvider,
    MockAIProvider,
    get_ai_provider,
    set_ai_provider,
)


def make_mock_groq_client(content: str):
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = content
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_care_deterministic_cycle_inquiry(async_client: AsyncClient, auth_headers: dict):
    # Without logged cycle data
    res_no_data = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "cycle_insight", "user_message": "When is my next period?"},
    )
    assert res_no_data.status_code == 200
    data_no = res_no_data.json()
    assert data_no["is_ai_generated"] is False
    assert "disclaimer" in data_no

    # Onboard with cycle
    await async_client.post(
        "/api/v1/onboarding/complete",
        headers=auth_headers,
        json={
            "last_period_start": "2026-08-10",
            "last_period_end": "2026-08-15",
            "usual_cycle_days": 28,
        },
    )

    res_with_data = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "cycle_insight", "user_message": "When is my next period?"},
    )
    assert res_with_data.status_code == 200
    data = res_with_data.json()
    assert data["is_ai_generated"] is False
    assert "Day" in data["response_text"]
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_care_device_help_inquiry(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "device_help", "user_message": "How do I connect my device?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "Bluetooth" in data["response_text"] or "wearable" in data["response_text"]


@pytest.mark.asyncio
async def test_care_personalized_inquiry_mock_ai(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "pain_help", "user_message": "I'm having terrible cramps and lower back pain"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False  # Truthful: MockAIProvider is rule-based mock
    assert "cramp" in data["response_text"].lower() or "heat" in data["response_text"].lower()
    assert "disclaimer" in data
    assert len(data["suggested_actions"]) > 0


@pytest.mark.asyncio
async def test_care_symptom_insight(async_client: AsyncClient, auth_headers: dict):
    # 1. Log some daily symptoms first
    await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={
            "log_date": "2026-08-16",
            "pain": 5,
            "mood": "fatigued",
            "symptoms": ["headache", "bloating", "cramps"],
        },
    )

    # 2. Query care with canonical intent="symptom_insight"
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "Why am I having bloating and headaches?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "symptom_insight"
    assert data["is_ai_generated"] is False
    assert "disclaimer" in data


@pytest.mark.asyncio
async def test_care_default_intent_is_wellness_help(async_client: AsyncClient, auth_headers: dict):
    # Omitting intent must default to wellness_help rather than cycle_insight
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"user_message": "Feeling tired today"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "wellness_help"
    assert data["is_ai_generated"] is False


@pytest.mark.asyncio
async def test_care_red_flag_emergency_triage(async_client: AsyncClient, auth_headers: dict):
    # 1. Test unbearable pain / fainting
    res1 = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "pain_help", "user_message": "I have unbearable pain and fainted earlier today"},
    )
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["is_ai_generated"] is False
    assert "URGENT CLINICAL SAFETY ADVISORY" in d1["response_text"]
    assert "Seek Emergency Care" in d1["suggested_actions"]

    # 2. Test heavy bleeding / hemorrhaging
    res2 = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "Experiencing heavy bleeding and soaking a pad every 30 minutes"},
    )
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["is_ai_generated"] is False
    assert "URGENT CLINICAL SAFETY ADVISORY" in d2["response_text"]


@pytest.mark.asyncio
async def test_care_explicit_intent_priority_over_keyword_inference(async_client: AsyncClient, auth_headers: dict):
    # When intent is explicitly "wellness_help", mentioning "when is my next period" should NOT hijack into cycle_insight
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "When is my next period? I feel tired."},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "wellness_help"


@pytest.mark.asyncio
async def test_care_rejects_invalid_intent_enum(async_client: AsyncClient, auth_headers: dict):
    # Invalid intent value outside CareIntentEnum must return 422
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "unsupported_chat_intent", "user_message": "Hello"},
    )
    assert res.status_code == 422


# ==============================================================================
# Groq AI Provider & Care Personalization Tests (Mocked - No Live Calls)
# ==============================================================================

@pytest.mark.asyncio
async def test_groq_provider_successful_structured_response():
    mock_client = make_mock_groq_client(
        json.dumps({
            "response": "Based on day 3, warm compression can help ease cramps.",
            "intent": "therapy_recommendation",
            "therapy_profile": "MODERATE",
        })
    )
    provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)

    res = await provider.generate_care_response(
        context={"cycle_day": 3, "phase": "menstrual"},
        user_message="My cramps feel moderately bad today",
        intent="pain_help",
    )

    assert res["is_ai_generated"] is True
    assert res["response_text"] == "Based on day 3, warm compression can help ease cramps."
    assert res["therapy_profile"] == "MODERATE"
    assert res["intent"] == "therapy_recommendation"

    # Verify model and SDK call arguments
    mock_client.chat.completions.create.assert_awaited_once()
    _, kwargs = mock_client.chat.completions.create.call_args
    assert kwargs["model"] == "openai/gpt-oss-120b"
    assert kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_groq_provider_malformed_json_fallback():
    mock_client = make_mock_groq_client("This is malformed non-json plain text response.")
    provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)

    res = await provider.generate_care_response(
        context={"cycle_day": 2, "phase": "menstrual"},
        user_message="I have bad cramps",
        intent="pain_help",
    )

    # Malformed output rejected, safe deterministic fallback executed
    assert res["is_ai_generated"] is False
    assert res["therapy_profile"] is None
    assert "cramp" in res["response_text"].lower()


@pytest.mark.asyncio
async def test_groq_provider_unsupported_profile_rejected():
    mock_client = make_mock_groq_client(
        json.dumps({
            "response": "Setting heater to extreme mode",
            "intent": "care",
            "therapy_profile": "EXTREME_HEAT",
        })
    )
    provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)

    res = await provider.generate_care_response(
        context={"cycle_day": 5},
        user_message="Need intense heat",
        intent="pain_help",
    )

    # Unsupported profile rejected, safe fallback executed
    assert res["is_ai_generated"] is False
    assert res["therapy_profile"] is None


@pytest.mark.asyncio
async def test_groq_provider_forbidden_hardware_fields_rejected():
    mock_client = make_mock_groq_client(
        json.dumps({
            "response": "Configuring raw heating element",
            "intent": "care",
            "therapy_profile": "MODERATE",
            "temperature": 43.5,
            "pwm": 255,
        })
    )
    provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)

    res = await provider.generate_care_response(
        context={"cycle_day": 4},
        user_message="Increase heater temperature",
        intent="pain_help",
    )

    # Hardware parameter violation rejected, safe fallback executed
    assert res["is_ai_generated"] is False
    assert res["therapy_profile"] is None


@pytest.mark.asyncio
async def test_groq_provider_timeout_fallback():
    from groq import APITimeoutError

    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=APITimeoutError(request=None))
    provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)

    res = await provider.generate_care_response(
        context={"cycle_day": 4},
        user_message="Having cramps",
        intent="pain_help",
    )

    assert res["is_ai_generated"] is False
    assert res["therapy_profile"] is None
    assert "cramp" in res["response_text"].lower()


@pytest.mark.asyncio
async def test_groq_provider_missing_api_key_fallback():
    provider = GroqAIProvider(api_key="")
    res = await provider.generate_care_response(
        context={"cycle_day": 4},
        user_message="Feeling fatigued",
        intent="wellness_help",
    )
    assert res["is_ai_generated"] is False
    assert res["therapy_profile"] is None
    assert "energy" in res["response_text"].lower() or "fatigue" in res["response_text"].lower()


@pytest.mark.asyncio
async def test_groq_provider_model_replaceable():
    mock_client = make_mock_groq_client(
        json.dumps({
            "response": "General wellness tips.",
            "intent": "care",
            "therapy_profile": None,
        })
    )
    provider = GroqAIProvider(
        api_key="test-mock-key",
        model="llama-3.3-70b-versatile",
        client=mock_client,
    )

    res = await provider.generate_care_response(
        context={"cycle_day": 10},
        user_message="Hello",
        intent="wellness_help",
    )
    assert res["is_ai_generated"] is True
    _, kwargs = mock_client.chat.completions.create.call_args
    assert kwargs["model"] == "llama-3.3-70b-versatile"


@pytest.mark.asyncio
async def test_care_interaction_with_groq_mock_provider(async_client: AsyncClient, auth_headers: dict):
    mock_client = make_mock_groq_client(
        json.dumps({
            "response": "At your current pain level, Moderate warmth has provided comfortable relief in past sessions.",
            "intent": "therapy_recommendation",
            "therapy_profile": "MODERATE",
        })
    )
    groq_provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)
    set_ai_provider(groq_provider)

    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What setting usually helps with my cramps?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is True
    assert data["therapy_profile"] == "MODERATE"
    assert "Start Moderate Thermal Therapy" in data["suggested_actions"]
    assert "Moderate warmth" in data["response_text"]


@pytest.mark.asyncio
async def test_care_red_flag_overrides_groq_ai(async_client: AsyncClient, auth_headers: dict):
    mock_client = make_mock_groq_client(
        json.dumps({
            "response": "Try strong heat.",
            "intent": "therapy_recommendation",
            "therapy_profile": "STRONG",
        })
    )
    groq_provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)
    set_ai_provider(groq_provider)

    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "pain_help", "user_message": "I have unbearable pain and fainted"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert data["therapy_profile"] is None
    assert "URGENT CLINICAL SAFETY ADVISORY" in data["response_text"]
    assert "Seek Emergency Care" in data["suggested_actions"]
    # Verify AI provider was NEVER invoked
    mock_client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_care_out_of_scope_redirect(async_client: AsyncClient, auth_headers: dict):
    mock_client = make_mock_groq_client(
        json.dumps({
            "response": "I'm here to help with your menstrual wellness, cycle data, symptoms, and MenoMate features. I can't help with unrelated topics.",
            "intent": "out_of_scope",
            "therapy_profile": None,
        })
    )
    groq_provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)
    set_ai_provider(groq_provider)

    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "other", "user_message": "Write me a Python program to sort numbers"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is True
    assert data["therapy_profile"] is None
    assert "menstrual wellness" in data["response_text"]


@pytest.mark.asyncio
async def test_care_personalization_context_with_verified_history(db_session: AsyncSession):
    import uuid
    from datetime import datetime, timezone
    from app.models.profile import Profile

    user_id = uuid.uuid4()
    profile = Profile(user_id=user_id, name="Test User", sensitivity_index=1.0)
    db_session.add(profile)
    await db_session.commit()

    # Add verified completed therapy sessions
    session1 = TherapySession(
        user_id=user_id,
        mode="standard",
        target_temperature_c=39.5,
        vibration_intensity=70,
        pain_before=6,
        pain_after=3,
        feedback="just_right",
        started_at=datetime.now(timezone.utc),
    )
    session2 = TherapySession(
        user_id=user_id,
        mode="standard",
        target_temperature_c=39.5,
        vibration_intensity=70,
        pain_before=5,
        pain_after=2,
        feedback="just_right",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add_all([session1, session2])
    await db_session.commit()

    ctx = await build_care_context(db_session, user_id=user_id, intent="pain_help")
    assert ctx["has_history"] is True
    assert "moderate_pain" in ctx["recent_pattern"]
    mod_pattern = ctx["recent_pattern"]["moderate_pain"]
    assert mod_pattern["preferred_profile"] == "MODERATE"
    assert mod_pattern["successful_sessions"] == 2
    assert "just_right" in ctx["recent_feedback"]


@pytest.mark.asyncio
async def test_care_personalization_context_without_history(db_session: AsyncSession):
    import uuid
    from app.models.profile import Profile

    user_id = uuid.uuid4()
    profile = Profile(user_id=user_id, name="New User", sensitivity_index=1.0)
    db_session.add(profile)
    await db_session.commit()

    ctx = await build_care_context(db_session, user_id=user_id, intent="pain_help")
    assert ctx["has_history"] is False
    assert "insufficient history" in ctx["history_note"].lower()
    assert ctx["recent_pattern"] == {}
    assert ctx["recent_feedback"] == []
