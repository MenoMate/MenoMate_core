"""Step 1 — active-session turns are transient input only (never stored)."""

import pytest
from httpx import AsyncClient

from app.db.base import Base


def _turns():
    return [
        {"role": "user", "text": "My cramps are worse today.", "topic": "symptom"},
        {"role": "care", "text": "Sorry to hear that.", "topic": "symptom"},
    ]


@pytest.mark.asyncio
async def test_recent_turns_accepted_and_transient(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={
            "intent": "cycle_insight",
            "user_message": "When is my next period?",
            "recent_turns": _turns(),
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False

    # Same deterministic reply with and without turns: turns change
    # nothing on deterministic paths and are not persisted.
    res2 = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "cycle_insight", "user_message": "When is my next period?"},
    )
    assert res2.status_code == 200
    assert res2.json()["response_text"] == data["response_text"]


@pytest.mark.asyncio
async def test_recent_turns_do_not_create_storage(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={
            "intent": "wellness_help",
            "user_message": "Hello",
            "recent_turns": _turns(),
        },
    )
    assert res.status_code == 200
    tables = set(Base.metadata.tables.keys())
    assert not {t for t in tables if "chat" in t or "turn" in t or "conversation" in t}


@pytest.mark.asyncio
async def test_recent_turns_bounded_and_validated(async_client: AsyncClient, auth_headers: dict):
    many = [
        {"role": "user" if i % 2 == 0 else "care", "text": f"turn {i}"}
        for i in range(20)
    ]
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "Hi", "recent_turns": many},
    )
    assert res.status_code == 200

    bad = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={
            "intent": "wellness_help",
            "user_message": "Hi",
            "recent_turns": [{"role": "system", "text": "x"}],
        },
    )
    assert bad.status_code == 422
