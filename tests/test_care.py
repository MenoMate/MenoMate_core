import pytest
from httpx import AsyncClient


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
    assert data["is_ai_generated"] is True
    assert "cramp" in data["response_text"].lower() or "heat" in data["response_text"].lower()
    assert "disclaimer" in data
    assert len(data["suggested_actions"]) > 0
