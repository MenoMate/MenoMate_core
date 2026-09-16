"""Step 4 — Mock is a deterministic context-aware fallback (same frames)."""

import json

import pytest
from httpx import AsyncClient

from app.services.ai_provider import MockAIProvider


def _ctx(**overrides):
    base = {"cycle_day": 5, "phase": "menstrual", "topic": "symptom"}
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_mock_quotes_logged_symptoms_not_in_message():
    mock = MockAIProvider()
    context = _ctx(recent_logs=[
        {"date": "2026-09-10", "pain": 4, "mood": None, "discharge": None,
         "flow": None, "symptoms": ["nausea"]},
    ])
    text = await mock.generate_reply(context, "I feel awful", intent="wellness_help")
    assert "nausea" in text  # from logs, not from the message


@pytest.mark.asyncio
async def test_mock_names_absence_instead_of_inventing():
    mock = MockAIProvider()
    text = await mock.generate_reply(_ctx(recent_logs=[]), "cramps again")
    assert "nothing" in text and "cramps" in text
    assert "None" not in text


@pytest.mark.asyncio
async def test_mock_never_renders_none_values():
    mock = MockAIProvider()
    text = await mock.generate_reply(
        {"topic": "wellness_general"}, "hello", intent="wellness_help"
    )
    assert "None" not in text


@pytest.mark.asyncio
async def test_mock_therapy_history_frame():
    mock = MockAIProvider()
    context = _ctx(
        topic="therapy",
        current_pain=6,
        has_history=True,
        recent_pattern={
            "moderate_pain": {
                "preferred_profile": "MODERATE",
                "successful_sessions": 2,
                "total_sessions": 3,
            }
        },
    )
    text = await mock.generate_reply(context, "what setting helps", intent="pain_help")
    assert "Moderate" in text
    assert "2 of 3" in text


@pytest.mark.asyncio
async def test_mock_insufficient_history_frame():
    mock = MockAIProvider()
    context = _ctx(topic="therapy", current_pain=5, has_history=False,
                   recent_pattern={})
    text = await mock.generate_reply(context, "what helps cramps", intent="pain_help")
    assert "can't personalize from history yet" in text


@pytest.mark.asyncio
async def test_mock_no_pain_needs_no_therapy():
    mock = MockAIProvider()
    context = _ctx(topic="therapy", current_pain=0, has_history=False,
                   recent_pattern={})
    text = await mock.generate_reply(context, "therapy?", intent="therapy_recommendation")
    assert "no therapy is needed" in text


@pytest.mark.asyncio
async def test_mock_prediction_line_where_available():
    mock = MockAIProvider()
    context = _ctx(topic="wellness_general", predicted_next_period="2026-10-01",
                   prediction_confidence="moderate")
    text = await mock.generate_reply(context, "how am I doing", intent="wellness_help")
    assert "2026-10-01" in text
    assert "moderate" in text


@pytest.mark.asyncio
async def test_mock_flag_stays_false():
    mock = MockAIProvider()
    res = await mock.generate_care_response(_ctx(), "cramps", intent="pain_help")
    assert res["is_ai_generated"] is False
    assert res["followup"] is None


@pytest.mark.asyncio
async def test_groq_mock_parity_on_profile_decision(
    async_client: AsyncClient, auth_headers: dict, db_session
):
    """Same evidence -> same profile reference via Groq and via Mock."""
    import uuid
    from datetime import date, datetime, timedelta, timezone
    from unittest.mock import AsyncMock, MagicMock
    from app.models.profile import Profile
    from app.models.cycle import Cycle
    from app.models.daily_log import DailyLog
    from app.models.therapy_session import TherapySession
    from app.services.ai_provider import GroqAIProvider, set_ai_provider
    from tests.conftest import make_token

    uid = uuid.uuid4()
    headers = {"Authorization": f"Bearer {make_token(uid)}"}
    db_session.add(Profile(user_id=uid, name="P", sensitivity_index=1.0))
    db_session.add(Cycle(
        user_id=uid,
        period_start=date.today() - timedelta(days=5),
        period_end=date.today() - timedelta(days=2),
    ))
    db_session.add(DailyLog(user_id=uid, log_date=date.today() - timedelta(days=1), pain=6))
    for _ in range(2):
        db_session.add(TherapySession(
            user_id=uid, mode="standard", target_temperature_c=39.5,
            vibration_intensity=70, pain_before=6, pain_after=3,
            feedback="just_right", started_at=datetime.now(timezone.utc),
        ))
    await db_session.commit()

    async def ask():
        return await async_client.post(
            "/api/v1/care/interactions",
            headers=headers,
            json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
        )

    # Groq path first (mocked model agrees with the evidence).
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "response": "Moderate warmth has worked for you.",
        "followup": None,
        "therapy_profile": "MODERATE",
    })
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    set_ai_provider(GroqAIProvider(api_key="test-mock-key", client=mock_client))
    groq_res = await ask()
    assert groq_res.json()["therapy_profile"] == "MODERATE"

    # Mock path: same deterministic decision surfaced in prose.
    set_ai_provider(MockAIProvider())
    mock_res = await ask()
    assert mock_res.json()["is_ai_generated"] is False
    assert "Moderate" in mock_res.json()["response_text"]
