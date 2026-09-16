"""Step 2 — topic routing at the API level (same question, same path)."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient


async def _onboard(client: AsyncClient, headers: dict):
    res = await client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json={
            "name": "Routing User",
            "last_period_start": str(date.today() - timedelta(days=5)),
            "last_period_end": str(date.today() - timedelta(days=2)),
            "usual_cycle_days": 28,
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_cycle_fact_question_routes_regardless_of_client_intent(
    async_client: AsyncClient, auth_headers: dict
):
    await _onboard(async_client, auth_headers)
    for intent in ("wellness_help", "other", "symptom_insight", "general_inquiry"):
        res = await async_client.post(
            "/api/v1/care/interactions",
            headers=auth_headers,
            json={"intent": intent, "user_message": "What day of my cycle am I on?"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["intent"] == intent  # request intent still echoed
        assert data["is_ai_generated"] is False
        assert "Day" in data["response_text"]


@pytest.mark.asyncio
async def test_prediction_question_via_freetext_is_deterministic(
    async_client: AsyncClient, auth_headers: dict
):
    await _onboard(async_client, auth_headers)
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "When is my next period?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "Day" in data["response_text"]


@pytest.mark.asyncio
async def test_chip_and_freetext_same_question_same_reply(
    async_client: AsyncClient, auth_headers: dict
):
    await _onboard(async_client, auth_headers)
    chip = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "cycle_insight", "user_message": "What's happening today?"},
    )
    free = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "What's happening today?"},
    )
    assert chip.status_code == 200 and free.status_code == 200
    assert chip.json()["response_text"] == free.json()["response_text"]
    assert chip.json()["is_ai_generated"] is False
    assert free.json()["is_ai_generated"] is False


@pytest.mark.asyncio
async def test_out_of_scope_fixed_refusal_without_ai(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "other", "user_message": "Write me a Python program to sort numbers"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "menstrual wellness" in data["response_text"]
    assert data["actions"] == []
    assert data["therapy_profile"] is None


@pytest.mark.asyncio
async def test_red_flag_paraphrase_cant_walk(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "pain_help", "user_message": "cramps so bad I cant walk straight"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "URGENT CLINICAL SAFETY ADVISORY" in data["response_text"]


@pytest.mark.asyncio
async def test_followup_with_turns_routes_without_error(
    async_client: AsyncClient, auth_headers: dict
):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={
            "intent": "wellness_help",
            "user_message": "What about yesterday?",
            "recent_turns": [
                {"role": "user", "text": "My cramps are worse today.", "topic": "symptom"},
            ],
        },
    )
    assert res.status_code == 200
    assert res.json()["is_ai_generated"] is False
