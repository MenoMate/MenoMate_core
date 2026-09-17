"""Step 3 — composer facts, select-then-enhance, validation gates."""

import json
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from app.services.care_composer import (
    compose_ai_reply,
    cross_check_therapy_profile,
    validate_explained_text,
    validate_followup,
)


def _facts(**overrides):
    base = {"cycle_day": 5, "phase": "menstrual"}
    base.update(overrides)
    return base


# --- Validation unit tests -------------------------------------------------

def test_fact_backed_numbers_pass():
    assert validate_explained_text(
        "Around day 5, cramping can feel uncomfortable.", _facts()
    ) is True


def test_invented_day_number_rejected():
    assert validate_explained_text(
        "Around day 99, cramping can feel uncomfortable.", _facts()
    ) is False


def test_unsupported_date_rejected():
    assert validate_explained_text(
        "Your next period is around 2030-01-01.", _facts()
    ) is False


def test_fact_date_and_human_form_accepted():
    facts = _facts(predicted_next_period="2026-09-12")
    assert validate_explained_text("Estimated around 2026-09-12.", facts) is True
    assert validate_explained_text("Estimated around Sep 12.", facts) is True


def test_population_phrase_rejected():
    assert validate_explained_text("Many users find heat helps.", _facts()) is False
    assert validate_explained_text("Many people start with gentle settings.", _facts()) is False


def test_empty_text_rejected():
    assert validate_explained_text("   ", _facts()) is False


def test_followup_rules():
    assert validate_followup(None) is True
    assert validate_followup("Is it sharper than usual?") is True
    assert validate_followup("Would you like to know more?") is False
    assert validate_followup("Anything else?") is False
    assert validate_followup("Not a question.") is False
    assert validate_followup("x" * 200 + "?") is False


def test_therapy_cross_check_accepts_without_evidence():
    facts = {"current_pain": 6, "band_evidence": {}}
    assert cross_check_therapy_profile("MODERATE", facts) == "MODERATE"
    assert cross_check_therapy_profile(None, facts) is None


def test_therapy_cross_check_rejects_no_pain():
    assert cross_check_therapy_profile("GENTLE", {"current_pain": 0}) is None


def test_therapy_cross_check_rejects_contradicted_band():
    facts = {
        "current_pain": 6,
        "band_evidence": {
            "moderate_pain": {
                "preferred_profile": "MODERATE",
                "successful_sessions": 3,
                "total_sessions": 3,
            }
        },
    }
    assert cross_check_therapy_profile("STRONG", facts) is None
    assert cross_check_therapy_profile("MODERATE", facts) == "MODERATE"


def test_composer_selects_facts_per_topic():
    context = {
        "cycle_day": 5,
        "phase": "menstrual",
        "recent_pain_avg": 6,
        "recent_logs": [{"date": "2026-08-16", "pain": 6, "mood": None,
                         "discharge": None, "flow": None, "symptoms": ["cramps"]}],
        "frequent_symptoms": ["cramps"],
        "recent_pattern": {},
        "recent_feedback": [],
        "has_history": False,
        "sensitivity_index": 1.0,
        "current_pain": 6,
    }
    symptom = compose_ai_reply("symptom", context)
    assert symptom.enhance is True and symptom.followup_allowed is True
    assert symptom.facts["cycle_day"] == 5
    assert "cramps" in symptom.facts["recent_symptoms"]

    lookup = compose_ai_reply("log_lookup", context)
    assert lookup.enhance is False
    assert "2026-08-16" in (lookup.base_text or "")
    assert "pain 6" in (lookup.base_text or "")

    wellness = compose_ai_reply("wellness_general", context)
    assert wellness.enhance is True and wellness.followup_allowed is False


# --- API tests: enhance + validation + fallback ----------------------------

def _groq(payload: dict):
    from unittest.mock import AsyncMock, MagicMock
    from app.services.ai_provider import GroqAIProvider, set_ai_provider

    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(payload)
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    provider = GroqAIProvider(api_key="test-mock-key", client=mock_client)
    set_ai_provider(provider)
    return mock_client


@pytest.mark.asyncio
async def test_model_numbers_outside_facts_cause_fallback(
    async_client: AsyncClient, auth_headers: dict
):
    _groq({
        "response": "Around day 99 your cramps will stop.",
        "followup": None,
        "therapy_profile": None,
    })
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "cramps today"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert "99" not in data["response_text"]


@pytest.mark.asyncio
async def test_contradicted_therapy_profile_becomes_null_keeping_text(
    async_client: AsyncClient, auth_headers: dict, db_session
):
    import uuid
    from datetime import datetime, timezone
    from app.models.profile import Profile
    from app.models.cycle import Cycle
    from app.models.daily_log import DailyLog
    from app.models.therapy_session import TherapySession
    from tests.conftest import make_token

    uid = uuid.uuid4()
    headers = {"Authorization": f"Bearer {make_token(uid)}"}
    db_session.add(Profile(user_id=uid, name="T", sensitivity_index=1.0))
    db_session.add(Cycle(
        user_id=uid,
        period_start=date.today() - timedelta(days=5),
        period_end=date.today() - timedelta(days=2),
    ))
    for _ in range(3):
        db_session.add(TherapySession(
            user_id=uid, mode="standard", target_temperature_c=39.5,
            vibration_intensity=70, pain_before=6, pain_after=3,
            feedback="just_right", started_at=datetime.now(timezone.utc),
        ))
    db_session.add(DailyLog(user_id=uid, log_date=date.today() - timedelta(days=1), pain=6))
    await db_session.commit()

    _groq({
        "response": "Strong heat may help.",
        "followup": None,
        "therapy_profile": "STRONG",
    })
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=headers,
        json={"intent": "pain_help", "user_message": "What setting helps my cramps?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is True
    assert data["therapy_profile"] is None  # contradicted MODERATE evidence
    assert "Strong heat" in data["response_text"]


@pytest.mark.asyncio
async def test_valid_followup_appended_and_banned_dropped(
    async_client: AsyncClient, auth_headers: dict
):
    _groq({
        "response": "Rest and warmth can help.",
        "followup": "Is it sharper than usual?",
        "therapy_profile": None,
    })
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "cramps today"},
    )
    assert "Is it sharper than usual?" in res.json()["response_text"]

    _groq({
        "response": "Rest and warmth can help.",
        "followup": "Would you like to know more?",
        "therapy_profile": None,
    })
    res2 = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "cramps today"},
    )
    assert "know more" not in res2.json()["response_text"]
    assert res2.json()["response_text"].count("?") == 0


@pytest.mark.asyncio
async def test_log_lookup_reads_back_exact_values(
    async_client: AsyncClient, auth_headers: dict
):
    log_day = date.today() - timedelta(days=2)
    log_res = await async_client.post(
        "/api/v1/logs",
        headers=auth_headers,
        json={
            "log_date": str(log_day),
            "pain": 5,
            "mood": ["tired"],
            "symptoms": [
                {"symptom_type": "headache", "severity": 4},
                {"symptom_type": "bloating", "severity": 3},
            ],
        },
    )
    assert log_res.status_code in (200, 201), log_res.text
    res = await async_client.post(
        "/api/v1/care/interactions",
        headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "What did I log on that day?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["is_ai_generated"] is False
    assert str(log_day) in data["response_text"]
    assert "pain 5" in data["response_text"]
    assert "tired" in data["response_text"]


# ---------------------------------------------------------------------------
# Real symptom rows end to end (seeded via API, never fabricated).
# ---------------------------------------------------------------------------

async def _seed_cramps_day(client, headers, day_offset: int, severity: int, pain=None):
    payload = {
        "log_date": str(date.today() - timedelta(days=day_offset)),
        "symptoms": [{"symptom_type": "cramps", "severity": severity}],
    }
    if pain is not None:
        payload["pain"] = pain
    res = await client.post("/api/v1/logs", headers=headers, json=payload)
    assert res.status_code in (200, 201), res.text
    return res.json()


@pytest.mark.asyncio
async def test_care_quotes_logged_cramps_with_severity(
    async_client: AsyncClient, auth_headers: dict
):
    await _seed_cramps_day(async_client, auth_headers, 1, 6, pain=6)
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "cramps today, why do I feel uncomfortable?"},
    )
    assert res.status_code == 200
    text = res.json()["response_text"]
    assert "cramps" in text
    assert "severity 6" in text


@pytest.mark.asyncio
async def test_single_observation_makes_no_frequency_claim(
    async_client: AsyncClient, auth_headers: dict
):
    await _seed_cramps_day(async_client, auth_headers, 1, 4, pain=4)
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "symptom_insight", "user_message": "cramps again"},
    )
    text = res.json()["response_text"].lower()
    assert "cramps" in text
    assert "often" not in text
    assert "you usually get" not in text


@pytest.mark.asyncio
async def test_repeated_rows_surface_in_frequent_symptoms(
    async_client: AsyncClient, auth_headers: dict, db_session
):
    from app.services.summary import get_current_cycle_summary
    from tests.conftest import TEST_USER_ID

    await async_client.post(
        "/api/v1/onboarding/complete", headers=auth_headers,
        json={
            "name": "Freq",
            "last_period_start": str(date.today() - timedelta(days=9)),
            "last_period_end": str(date.today() - timedelta(days=6)),
        },
    )
    await _seed_cramps_day(async_client, auth_headers, 5, 5, pain=5)
    await _seed_cramps_day(async_client, auth_headers, 3, 6, pain=6)
    await _seed_cramps_day(async_client, auth_headers, 1, 4, pain=4)
    summary = await get_current_cycle_summary(db_session, TEST_USER_ID)
    assert "cramps" in summary["frequent_symptoms"]


@pytest.mark.asyncio
async def test_null_pain_never_rendered(async_client: AsyncClient, auth_headers: dict):
    day = date.today() - timedelta(days=1)
    res = await async_client.post(
        "/api/v1/logs", headers=auth_headers,
        json={"log_date": str(day), "mood": ["calm"],
              "symptoms": [{"symptom_type": "headache", "severity": 2}]},
    )
    assert res.status_code in (200, 201)
    res = await async_client.post(
        "/api/v1/care/interactions", headers=auth_headers,
        json={"intent": "wellness_help", "user_message": "What did I log on that day?"},
    )
    text = res.json()["response_text"]
    assert "pain None" not in text
    assert "headache" in text
