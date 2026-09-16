"""Step 7 — deterministic /recommend output sources therapy context."""

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.services.ai_provider import GroqAIProvider, set_ai_provider


async def _seed_pain(client: AsyncClient, headers: dict, pain: int = 6):
    res = await client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json={
            "name": "Therapy User",
            "last_period_start": str(date.today() - timedelta(days=5)),
            "last_period_end": str(date.today() - timedelta(days=2)),
            "usual_cycle_days": 28,
        },
    )
    assert res.status_code == 201, res.text
    log = await client.post(
        "/api/v1/logs",
        headers=headers,
        json={"log_date": str(date.today() - timedelta(days=1)), "pain": pain},
    )
    assert log.status_code in (200, 201), log.text


def _groq(payload: dict):
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(payload)
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    set_ai_provider(GroqAIProvider(api_key="test-mock-key", client=mock_client))
    return mock_client


@pytest.mark.asyncio
async def test_recommend_mismatch_nulls_model_profile(async_client: AsyncClient, auth_headers: dict):
    """Pain 6 -> deterministic MODERATE; a STRONG model pick is nulled
    by the recommend rule even with no session history at all."""
    await _seed_pain(async_client, auth_headers)
    _groq({"response": "Strong heat may help.", "followup": None, "therapy_profile": "STRONG"})
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is True
    assert data["therapy_profile"] is None


@pytest.mark.asyncio
async def test_recommend_match_keeps_model_profile(async_client: AsyncClient, auth_headers: dict):
    await _seed_pain(async_client, auth_headers)
    _groq({"response": "Moderate warmth fits.", "followup": None, "therapy_profile": "MODERATE"})
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
    )
    assert res.json()["therapy_profile"] == "MODERATE"


@pytest.mark.asyncio
async def test_prompt_excludes_hardware_numbers(async_client: AsyncClient, auth_headers: dict):
    await _seed_pain(async_client, auth_headers)
    mock_client = _groq({"response": "Moderate warmth fits.", "followup": None, "therapy_profile": "MODERATE"})
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
    )
    assert res.status_code == 200
    _, kwargs = mock_client.chat.completions.create.call_args
    prompt_json = kwargs["messages"][1]["content"]
    assert "target_temperature" not in prompt_json
    assert "duration_minutes" not in prompt_json
    assert "vibration_intensity" not in prompt_json
    # The deterministic subset (label + pain) is present instead.
    assert "MODERATE" in prompt_json


@pytest.mark.asyncio
async def test_mock_therapy_frame_uses_approved_profile(async_client: AsyncClient, auth_headers: dict):
    await _seed_pain(async_client, auth_headers)
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "approved Moderate" in data["response_text"]


@pytest.mark.asyncio
async def test_response_carries_no_executable_values(async_client: AsyncClient, auth_headers: dict):
    await _seed_pain(async_client, auth_headers)
    _groq({"response": "Moderate warmth fits.", "followup": None, "therapy_profile": "MODERATE"})
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
    )
    body = res.json()
    for key in ("temperature", "target_temperature_c", "duration_minutes",
                "pwm", "vibration_intensity", "gpio", "ble_command"):
        assert key not in body
