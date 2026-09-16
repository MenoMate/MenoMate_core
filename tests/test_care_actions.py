"""Step 6 — tier + semantic action IDs are deterministic (backend)."""

from datetime import date, timedelta

import pytest
from httpx import AsyncClient


async def _onboard(client: AsyncClient, headers: dict):
    res = await client.post(
        "/api/v1/onboarding/complete",
        headers=headers,
        json={
            "name": "Action User",
            "last_period_start": str(date.today() - timedelta(days=5)),
            "last_period_end": str(date.today() - timedelta(days=2)),
            "usual_cycle_days": 28,
        },
    )
    assert res.status_code == 201, res.text


@pytest.mark.asyncio
async def test_tier_values_per_path(async_client: AsyncClient, auth_headers: dict):
    await _onboard(async_client, auth_headers)

    urgent = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "pain_help", "user_message": "unbearable pain and fainted"},
    )
    assert urgent.json()["tier"] == "urgent"

    advisory = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "Do I have endometriosis?"},
    )
    assert advisory.json()["tier"] == "advisory"

    info = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "cycle_insight", "user_message": "What day am I on?"},
    )
    assert info.json()["tier"] == "info"

    oos = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "other", "user_message": "Write python code"},
    )
    assert oos.json()["tier"] == "info"


@pytest.mark.asyncio
async def test_actions_deterministic_and_shaped(async_client: AsyncClient, auth_headers: dict):
    await _onboard(async_client, auth_headers)
    payload = {"intent": "cycle_insight", "user_message": "What day am I on?"}
    r1 = await async_client.post("/api/v1/care/interactions", headers=auth_headers, json=payload)
    r2 = await async_client.post("/api/v1/care/interactions", headers=auth_headers, json=payload)
    assert r1.json()["actions"] == r2.json()["actions"]
    assert [a["id"] for a in r1.json()["actions"]] == ["open_calendar", "open_history"]
    for action in r1.json()["actions"]:
        assert set(action.keys()) == {"id", "label"}
    assert "suggested_actions" not in r1.json()


@pytest.mark.asyncio
async def test_awaiting_state_adds_log_period_start(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/onboarding/complete",
        headers=auth_headers,
        json={
            "name": "Awaiting User",
            "last_period_start": str(date.today() - timedelta(days=40)),
            "last_period_end": str(date.today() - timedelta(days=36)),
            "usual_cycle_days": 28,
        },
    )
    assert res.status_code == 201, res.text
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "cycle_insight", "user_message": "When is my next period?"},
    )
    assert res.status_code == 200
    ids = [a["id"] for a in res.json()["actions"]]
    assert ids == ["open_calendar", "open_history", "log_period_start"]


@pytest.mark.asyncio
async def test_therapy_without_profile_offers_connect(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
    )
    assert res.status_code == 200
    ids = [a["id"] for a in res.json()["actions"]]
    assert ids == ["connect_wearable", "open_logger"]


@pytest.mark.asyncio
async def test_out_of_scope_has_no_actions(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "other", "user_message": "Who won the football match?"},
    )
    assert res.status_code == 200
    assert res.json()["actions"] == []
