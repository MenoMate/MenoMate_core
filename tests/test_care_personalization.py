import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.security import get_current_user
from app.main import app
from app.models.care_memory import CareMemory
from app.models.cycle import Cycle
from app.models.daily_log import DailyLog
from app.models.profile import Profile
from app.models.symptom_log import SymptomLog
from app.models.therapy_session import TherapySession
from app.services.pattern_engine import analyze_user_patterns
from app.services.personal_context import build_personal_care_context


@pytest.mark.asyncio
async def test_pattern_engine_no_logs_and_incomplete_cycles():
    today = date(2026, 11, 20)
    c1 = Cycle(id=1, user_id=uuid.uuid4(), period_start=date(2026, 11, 15), period_end=None)
    res = analyze_user_patterns(cycles=[c1], logs=[], sessions=[], today=today)
    assert res.insights == []
    assert res.tracking_completeness.logged_days == 0
    assert res.tracking_completeness.incomplete_cycles == 1
    assert res.tracking_completeness.complete_cycles == 0
    assert any("No daily logs" in n for n in res.tracking_completeness.missing_data_notes)
    assert len(res.insufficient_data_reasons) >= 1


@pytest.mark.asyncio
async def test_pattern_engine_missing_pain_not_imputed_as_zero():
    today = date(2026, 11, 20)
    uid = uuid.uuid4()
    c1 = Cycle(id=1, user_id=uid, period_start=date(2026, 10, 15), period_end=date(2026, 10, 19))
    c2 = Cycle(id=2, user_id=uid, period_start=date(2026, 11, 15), period_end=date(2026, 11, 19))
    logs = [
        # Cycle 1: two logs with explicit pain 2 and 4 -> avg 3.0; one log with pain=None
        DailyLog(id=1, user_id=uid, log_date=date(2026, 10, 15), pain=2, symptoms=[]),
        DailyLog(id=2, user_id=uid, log_date=date(2026, 10, 16), pain=4, symptoms=[]),
        DailyLog(id=3, user_id=uid, log_date=date(2026, 10, 17), pain=None, symptoms=[]),
        # Cycle 2: two logs with pain 6 and 8 -> avg 7.0
        DailyLog(id=4, user_id=uid, log_date=date(2026, 11, 15), pain=6, symptoms=[]),
        DailyLog(id=5, user_id=uid, log_date=date(2026, 11, 16), pain=8, symptoms=[]),
    ]
    res = analyze_user_patterns(cycles=[c1, c2], logs=logs, sessions=[], today=today)
    assert res.pain_trend is not None
    assert res.pain_trend["previous_avg_pain"] == 3.0
    assert res.pain_trend["recent_avg_pain"] == 7.0
    assert res.pain_trend["direction"] == "higher"


@pytest.mark.asyncio
async def test_pattern_engine_cycle_day_symptom_and_mood_cooccurrence():
    today = date(2026, 11, 20)
    uid = uuid.uuid4()
    c1 = Cycle(id=1, user_id=uid, period_start=date(2026, 10, 15), period_end=date(2026, 10, 19))
    c2 = Cycle(id=2, user_id=uid, period_start=date(2026, 11, 15), period_end=date(2026, 11, 19))
    l1 = DailyLog(id=1, user_id=uid, log_date=date(2026, 10, 15), pain=6, mood='["anxious"]')
    l1.symptoms = [SymptomLog(id=1, daily_log_id=1, symptom_type="cramps", severity=4)]
    l2 = DailyLog(id=2, user_id=uid, log_date=date(2026, 11, 15), pain=7, mood='["anxious"]')
    l2.symptoms = [SymptomLog(id=2, daily_log_id=2, symptom_type="cramps", severity=4)]
    l3 = DailyLog(id=3, user_id=uid, log_date=date(2026, 11, 16), pain=5, mood='["calm"]')
    l3.symptoms = [SymptomLog(id=3, daily_log_id=3, symptom_type="fatigue", severity=3)]

    res = analyze_user_patterns(cycles=[c1, c2], logs=[l1, l2, l3], sessions=[], today=today)
    types = {i.insight_type for i in res.insights}
    assert "frequent_symptom" in types
    assert "cycle_day_pattern" in types
    assert "mood_pain_cooccurrence" in types
    coocc = next(i for i in res.insights if i.insight_type == "mood_pain_cooccurrence")
    assert "does not show cause" in coocc.explanation


@pytest.mark.asyncio
async def test_personal_context_and_cross_user_isolation(async_client, db_session):
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    db_session.add(Profile(user_id=user_a, name="Alice", timezone="UTC"))
    db_session.add(Profile(user_id=user_b, name="Bob", timezone="UTC"))
    db_session.add(
        CareMemory(
            user_id=user_b,
            category="care_preference",
            key="tone",
            value="Secret Bob preference",
            source="user_explicit",
        )
    )
    await db_session.commit()

    ctx_a = await build_personal_care_context(db_session, user_a)
    assert ctx_a.memories == []
    assert ctx_a.has_history is False

    # API cross-user check for CareMemory CRUD
    app.dependency_overrides[get_current_user] = lambda: user_a
    create_resp = await async_client.post(
        "/api/v1/care/memories",
        json={"category": "care_preference", "key": "tone", "value": "Keep it brief"},
    )
    assert create_resp.status_code == 201
    mem_a_id = create_resp.json()["id"]

    list_a = await async_client.get("/api/v1/care/memories")
    assert list_a.status_code == 200
    assert len(list_a.json()) == 1
    assert list_a.json()[0]["value"] == "Keep it brief"

    # Switch to User B: cannot see, patch, or delete User A's memory
    app.dependency_overrides[get_current_user] = lambda: user_b
    patch_cross = await async_client.patch(
        f"/api/v1/care/memories/{mem_a_id}",
        json={"value": "Hacked"},
    )
    assert patch_cross.status_code == 404
    del_cross = await async_client.delete(f"/api/v1/care/memories/{mem_a_id}")
    assert del_cross.status_code == 404
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_device_session_statuses_and_feedback(async_client, db_session):
    user_id = uuid.uuid4()
    db_session.add(Profile(user_id=user_id, name="Test", timezone="UTC"))
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: user_id
    r1 = await async_client.post(
        "/api/v1/therapy/sessions",
        json={
            "mode": "gentle",
            "requested_heat_level": 1,
            "requested_duration_minutes": 10,
            "command_status": "acknowledged",
            "ack_status": "acknowledged",
            "session_status": "completed",
            "pain_before": 6,
            "pain_after": 3,
            "comfort_rating": "comfortable",
            "noticed_improvement": True,
        },
    )
    assert r1.status_code == 201
    data1 = r1.json()
    assert data1["command_status"] == "acknowledged"
    assert data1["session_status"] == "completed"
    assert data1["comfort_rating"] == "comfortable"
    assert data1["noticed_improvement"] is True

    r2 = await async_client.post(
        "/api/v1/therapy/sessions",
        json={
            "mode": "gentle",
            "requested_heat_level": 1,
            "command_status": "sent",
            "ack_status": "timeout",
            "session_status": "failed",
            "pain_before": 5,
        },
    )
    assert r2.status_code == 201

    insights_resp = await async_client.get("/api/v1/care/insights")
    assert insights_resp.status_code == 200
    summary = insights_resp.json()["device_preference_summary"]
    assert summary["total_sessions"] == 2
    assert summary["confirmed_completed_sessions"] == 1
    assert summary["most_selected_mode"] == "gentle"
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_care_pattern_summary_and_red_flag_preserved(async_client, db_session, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    user_id = uuid.uuid4()
    db_session.add(Profile(user_id=user_id, name="Test", timezone="UTC"))
    await db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: user_id

    # Pattern summary with no logs -> honest insufficient-history response
    resp = await async_client.post(
        "/api/v1/care/interactions",
        json={
            "intent": "pattern_summary",
            "user_message": "Can you summarize the patterns you've noticed in my recent cycles?",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "info"
    assert body["is_ai_generated"] is False
    assert "0 logged days" in body["response_text"]

    # Red-flag safety remains deterministic and urgent
    urgent = await async_client.post(
        "/api/v1/care/interactions",
        json={
            "intent": "pattern_summary",
            "user_message": "I have unbearable pain and fainted today",
        },
    )
    assert urgent.status_code == 200
    assert urgent.json()["tier"] == "urgent"
    assert urgent.json()["is_ai_generated"] is False
    app.dependency_overrides.clear()
