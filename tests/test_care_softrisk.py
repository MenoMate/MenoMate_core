"""Step 5 — deterministic soft-risk interception (unit + API)."""

import pytest
from httpx import AsyncClient

from app.services.care_topics import (
    RISK_ADVISORY,
    RISK_DIAGNOSIS,
    RISK_MEDICATION,
    RISK_NONE,
    classify_soft_risk,
)


def test_diagnosis_asks_intercepted():
    for msg in (
        "Do I have endometriosis?",
        "Could I have PCOS?",
        "What is wrong with me?",
        "Am I pregnant?",
        "Should I take a pregnancy test?",
    ):
        assert classify_soft_risk(msg) == RISK_DIAGNOSIS, msg


def test_medication_asks_intercepted():
    for msg in (
        "What dose of ibuprofen should I take?",
        "Should I take painkillers?",
        "How many mg can I take?",
        "Is paracetamol safe?",
        "Should I start birth control?",
    ):
        assert classify_soft_risk(msg) == RISK_MEDICATION, msg


def test_advisory_escalation_detected():
    for msg in (
        "cramps getting worse each month",
        "painkillers don't work anymore",
        "I can't cope with the pain",
        "nothing helps my cramps",
    ):
        assert classify_soft_risk(msg) == RISK_ADVISORY, msg


def test_plain_intensity_is_not_soft_risk():
    for msg in (
        "I'm having terrible cramps and lower back pain",
        "When is my next period?",
        "Feeling tired today",
        "What setting usually helps with my cramps?",
    ):
        assert classify_soft_risk(msg) == RISK_NONE, msg


@pytest.mark.asyncio
async def test_diagnosis_fixed_frame(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "Do I have endometriosis?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "can't diagnose" in data["response_text"]
    assert [a["id"] for a in data["actions"]] == ["open_logger"]


@pytest.mark.asyncio
async def test_medication_fixed_frame(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "pain_help", "user_message": "What dose of ibuprofen should I take?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "can't recommend" in data["response_text"]
    # No dosage recommendation leaks from the fixed frame.
    import re

    assert re.search(r"\d+\s*mg", data["response_text"], re.IGNORECASE) is None


@pytest.mark.asyncio
async def test_advisory_keeps_caution_lead(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={
            "intent": "pain_help",
            "user_message": "cramps getting worse each month, painkillers don't work",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["response_text"].startswith("That sounds really tough")
    assert data["is_ai_generated"] is False  # Mock fallback under the lead


@pytest.mark.asyncio
async def test_red_flag_still_beats_soft_risk(async_client: AsyncClient, auth_headers: dict):
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={
            "intent": "pain_help",
            "user_message": "unbearable pain, should I take painkillers?",
        },
    )
    assert res.status_code == 200
    assert "URGENT CLINICAL SAFETY ADVISORY" in res.json()["response_text"]
