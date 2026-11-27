import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.schemas.care import CareIntentEnum
from app.services.care import apply_care_consent_filter, handle_care_interaction
from app.services.pattern_engine import analyze_user_patterns
from app.models.cycle import Cycle
from app.models.daily_log import DailyLog
from app.models.profile import Profile
from app.models.therapy_session import TherapySession
from app.services.ai_provider import BaseAIProvider


def test_pattern_engine_parity_window_and_tracked_cycles_denominator():
    """Matches the Dart local_insights_engine parity fixture."""
    today = date(2026, 6, 15)
    # Earliest cycle started 14 days ago -> effective window = 15 days (inclusive).
    c1_start = today - timedelta(days=14)
    c2_start = today - timedelta(days=4)

    cycles = [
        SimpleNamespace(
            id=1,
            period_start=c1_start,
            period_end=c1_start + timedelta(days=4),
        ),
        SimpleNamespace(
            id=2,
            period_start=c2_start,
            period_end=c2_start + timedelta(days=3),
        ),
        # Older cycle outside 90-day window without logs must not inflate denominator
        SimpleNamespace(
            id=3,
            period_start=today - timedelta(days=120),
            period_end=today - timedelta(days=116),
        ),
    ]

    logs = [
        # Cycle 1, Day 1 (pain=2, cramps)
        SimpleNamespace(
            id=1,
            log_date=c1_start,
            pain=2,
            mood=["calm"],
            symptoms=[SimpleNamespace(symptom_type="cramps", severity=2)],
        ),
        # Cycle 1, Day 2 (pain=None -> must not be imputed as 0)
        SimpleNamespace(
            id=2,
            log_date=c1_start + timedelta(days=1),
            pain=None,
            mood=[],
            symptoms=[SimpleNamespace(symptom_type="cramps", severity=None)],
        ),
        # Cycle 2, Day 2 (pain=7, cramps)
        SimpleNamespace(
            id=3,
            log_date=c2_start + timedelta(days=1),
            pain=7,
            mood=["irritable"],
            symptoms=[SimpleNamespace(symptom_type="cramps", severity=4)],
        ),
        # Cycle 2, Day 3 (pain=8)
        SimpleNamespace(
            id=4,
            log_date=c2_start + timedelta(days=2),
            pain=8,
            mood=[],
            symptoms=[],
        ),
    ]

    result = analyze_user_patterns(
        cycles=cycles,
        logs=logs,
        sessions=[],
        today=today,
        window_days=90,
    )

    assert result.tracking_completeness.logged_days == 4
    # Effective window starts at c1_start (15 days inclusive) rather than 90 days
    assert result.tracking_completeness.window_days == 15
    assert result.tracking_completeness.coverage_ratio == pytest.approx(round(4 / 15, 2))

    cramps = next(s for s in result.frequent_symptoms if s["symptom"] == "cramps")
    assert cramps["count"] == 3
    # Cycle 1 has only 1 non-null pain log because pain=None is never imputed as 0
    assert result.pain_trend is None

    cd_insights = [i for i in result.insights if i.insight_type == "cycle_day_pattern"]
    assert cd_insights, "Expected cycle_day_pattern insight when both tracked cycles match days 1-2"
    assert "2 of your 2 tracked cycles" in cd_insights[0].explanation


def test_apply_care_consent_filter_strips_disallowed_and_sensitive_keys():
    ctx = {
        "user_id": "secret-id",
        "email": "user@example.com",
        "conditions": ["PCOS"],
        "medications": ["ibuprofen"],
        "intent": "pattern_summary",
        "topic": "pattern_summary",
        "cycle_day": 14,
        "phase": "ovulation",
        "frequent_symptoms": [{"symptom_type": "cramps", "count": 3}],
        "recent_therapy_sessions": [{"profile": "warm_relief"}],
        "memories": [{"key": "pref", "value": "gentle"}],
    }
    facts = {
        "cycle_day": 14,
        "frequent_symptoms": ["cramps"],
        "recent_therapy_sessions": ["warm_relief"],
        "memories": ["gentle"],
        "medications": ["ibuprofen"],
    }

    # Consent denied for external provider -> zero personal records
    no_ctx, no_facts = apply_care_consent_filter(
        ctx, facts, consent_granted=False, is_mock_provider=False
    )
    assert no_ctx == {"intent": "pattern_summary", "topic": "pattern_summary", "consent_granted": False}
    assert no_facts == {"consent_granted": False}

    # Consent granted with only ["cycles"] -> daily_logs, device_history, memories, and sensitive keys stripped
    cyc_ctx, cyc_facts = apply_care_consent_filter(
        ctx,
        facts,
        consent_granted=True,
        allowed_categories=["cycles"],
        is_mock_provider=False,
    )
    assert cyc_ctx["cycle_day"] == 14
    assert cyc_ctx["phase"] == "ovulation"
    for forbidden in (
        "user_id",
        "email",
        "conditions",
        "medications",
        "frequent_symptoms",
        "recent_therapy_sessions",
        "memories",
    ):
        assert forbidden not in cyc_ctx
        assert forbidden not in cyc_facts


@pytest.mark.asyncio
async def test_handle_care_interaction_enforces_consent_before_external_llm(
    db_session, monkeypatch
):
    class RecordingExternalProvider(BaseAIProvider):
        def __init__(self):
            self.calls = []

        async def generate_reply(self, context, user_message, intent):
            return "Generic wellness guidance."

        async def generate_care_response(
            self, context, user_message, intent, facts, topic, recent_turns=None
        ):
            self.calls.append({"context": context, "facts": facts})
            return {
                "response_text": "Gentle warmth and rest may help.",
                "is_ai_generated": True,
                "followup": None,
                "therapy_profile": None,
            }

    recorder = RecordingExternalProvider()
    monkeypatch.setattr("app.services.care.get_ai_provider", lambda: recorder)

    user_id = uuid.uuid4()
    today = date.today()
    db_session.add(Profile(user_id=user_id, name="Alice", timezone="UTC"))
    db_session.add(Cycle(user_id=user_id, period_start=today - timedelta(days=5)))
    db_session.add(DailyLog(user_id=user_id, log_date=today, pain=6, mood='["tired"]'))
    await db_session.commit()

    # 1. Consent NOT granted -> external provider receives zero personal records
    await handle_care_interaction(
        db=db_session,
        user_id=user_id,
        intent=CareIntentEnum.symptom_insight,
        user_message="Why do I feel tired and crampy?",
        consent_granted=False,
    )
    assert len(recorder.calls) == 1
    sent_ctx = recorder.calls[0]["context"]
    assert "frequent_symptoms" not in sent_ctx
    assert "cycle_day" not in sent_ctx
    assert "recent_therapy_sessions" not in sent_ctx

    # 2. Consent granted for ["cycles"] only -> cycle_day present, daily_logs & device stripped
    await handle_care_interaction(
        db=db_session,
        user_id=user_id,
        intent=CareIntentEnum.symptom_insight,
        user_message="How does my cycle relate to symptoms?",
        consent_granted=True,
        allowed_categories=["cycles"],
    )
    assert len(recorder.calls) == 2
    sent_ctx2 = recorder.calls[1]["context"]
    assert "cycle_day" in sent_ctx2
    assert "frequent_symptoms" not in sent_ctx2
    assert "recent_therapy_sessions" not in sent_ctx2
