from datetime import date
import uuid
import pytest
from app.models.cycle import Cycle
from app.models.profile import Profile
from app.services.cycle_calculator import (
    calculate_cycle_lengths,
    calculate_period_length,
    estimate_phase,
    predict_next_cycle,
)


def _mk_cycle(uid, start, end=None):
    return Cycle(user_id=uid, period_start=start, period_end=end)


# ---------------------------------------------------------------------------
# 1. Start-to-start cycle calculation (Rule A)
# ---------------------------------------------------------------------------
def test_start_to_start_cycle_length_calculation():
    """
    Critical requirement:
    Cycle length is measured between consecutive period starts, NOT bleeding duration!
    Period A: Aug 10 - Aug 14
    Period B: Sep 08 - Sep 12
    Cycle length = Sep 08 - Aug 10 = 29 days
    """
    uid = uuid.uuid4()
    p1 = Cycle(user_id=uid, period_start=date(2026, 8, 10), period_end=date(2026, 8, 14))
    p2 = Cycle(user_id=uid, period_start=date(2026, 9, 8), period_end=date(2026, 9, 12))
    p3 = Cycle(user_id=uid, period_start=date(2026, 10, 6), period_end=date(2026, 10, 10))

    # Explicit today AFTER all periods so all are observed (deterministic).
    lengths = calculate_cycle_lengths([p1, p2, p3], today=date(2026, 10, 15))
    assert len(lengths) == 2
    assert lengths[0] == 29  # Aug 10 to Sep 8 = 29 days
    assert lengths[1] == 28  # Sep 8 to Oct 6 = 28 days


# ---------------------------------------------------------------------------
# 2. Period duration (Rule A): period_end - period_start + 1
# ---------------------------------------------------------------------------
def test_period_length_calculation():
    cycle = Cycle(
        user_id=uuid.uuid4(),
        period_start=date(2026, 8, 10),
        period_end=date(2026, 8, 14),
    )
    # Aug 10 to Aug 14 inclusive = 5 days
    assert calculate_period_length(cycle) == 5

    ongoing_cycle = Cycle(
        user_id=uuid.uuid4(),
        period_start=date(2026, 8, 10),
        period_end=None,
    )
    assert calculate_period_length(ongoing_cycle) is None


# ---------------------------------------------------------------------------
# 3. Future periods excluded from prediction (Rule B)
# ---------------------------------------------------------------------------
def test_future_periods_excluded_from_prediction():
    uid = uuid.uuid4()
    p1 = _mk_cycle(uid, date(2026, 8, 10), date(2026, 8, 14))
    p2 = _mk_cycle(uid, date(2026, 9, 8), date(2026, 9, 12))
    future = _mk_cycle(uid, date(2026, 10, 6), date(2026, 10, 10))
    today = date(2026, 9, 11)

    observed_only = calculate_cycle_lengths([p1, p2], today=today)
    with_future = calculate_cycle_lengths([p1, p2, future], today=today)
    assert observed_only == [29]
    # Future-logged period must NOT contribute an extra interval.
    assert with_future == observed_only

    # Interval where the NEXT period starts in the future is excluded,
    # even if the current period is observed.
    p_today = _mk_cycle(uid, date(2026, 9, 11), date(2026, 9, 15))
    assert calculate_cycle_lengths([p1, p_today], today=today) == [32]
    assert calculate_cycle_lengths([p_today, future], today=today) == []


def test_future_period_start_equal_today_is_observed():
    """Boundary: period_start == today counts as observed (date-only semantics)."""
    uid = uuid.uuid4()
    p1 = _mk_cycle(uid, date(2026, 8, 10), date(2026, 8, 14))
    p2 = _mk_cycle(uid, date(2026, 9, 11), date(2026, 9, 15))
    lengths = calculate_cycle_lengths([p1, p2], today=date(2026, 9, 11))
    assert lengths == [32]


# ---------------------------------------------------------------------------
# 4-7. Confidence tiers (Rule E)
# ---------------------------------------------------------------------------
def test_one_interval_low_confidence():
    r = predict_next_cycle([28])
    assert r.predicted_cycle_length == 28
    assert r.confidence == "low"
    assert r.source == "history"


def test_two_intervals_low_confidence():
    r = predict_next_cycle([28, 30])
    assert r.confidence == "low", "1-2 intervals must never be moderate (Rule E)"
    assert r.source == "history"


def test_three_intervals_moderate_when_stable():
    r = predict_next_cycle([28, 29, 28])
    assert r.confidence == "moderate"
    assert r.variability_std_dev is not None
    assert r.variability_std_dev <= 4.0


def test_three_intervals_low_when_variable():
    # High spread with 3 intervals -> MAD large -> low, not moderate.
    r = predict_next_cycle([20, 30, 40])
    assert r.confidence == "low"


def test_six_intervals_high_when_stable():
    r = predict_next_cycle([28, 28, 29, 28, 29, 28])
    assert r.confidence == "high"
    assert r.variability_std_dev is not None
    assert r.variability_std_dev <= 3.0


def test_six_intervals_moderate_or_low_when_variable():
    r = predict_next_cycle([22, 35, 24, 38, 26, 40])
    assert r.confidence in ("low", "moderate")
    assert r.confidence != "high"


# ---------------------------------------------------------------------------
# 8. Outlier handling (Rule C)
# ---------------------------------------------------------------------------
def test_outlier_cycle_handled_robustly():
    # Five stable 28s + one 60-day outlier. Plain WMA would give ~37.
    r = predict_next_cycle([28, 28, 28, 28, 28, 60])
    assert r.predicted_cycle_length == 28, f"outlier dragged prediction to {r.predicted_cycle_length}"
    # And a single mid-history outlier is dropped too.
    r2 = predict_next_cycle([28, 29, 55, 28, 29])
    assert abs(r2.predicted_cycle_length - 28) <= 2


def test_prediction_uses_up_to_six_most_recent():
    # 8 intervals: oldest two (20, 20) should be ignored; recent six are ~28.
    lengths = [20, 20, 28, 28, 28, 28, 28, 28]
    r = predict_next_cycle(lengths)
    assert r.predicted_cycle_length == 28


# ---------------------------------------------------------------------------
# 9-10. Irregular vs stable (Rule C)
# ---------------------------------------------------------------------------
def test_irregular_cycles_lower_confidence():
    stable = predict_next_cycle([28, 28, 29, 28, 29, 28])
    irregular = predict_next_cycle([22, 35, 24, 38, 26, 40])
    assert stable.confidence == "high"
    assert irregular.confidence != "high"
    assert irregular.variability_std_dev > stable.variability_std_dev


def test_stable_cycles_high_confidence():
    r = predict_next_cycle([28, 28, 28, 28, 28, 28])
    assert r.predicted_cycle_length == 28
    assert r.confidence == "high"
    assert r.variability_std_dev == 0.0


# ---------------------------------------------------------------------------
# 11-12. Insufficient history + user baseline (Rule D)
# ---------------------------------------------------------------------------
def test_prediction_insufficient_history():
    # 0 cycles, no usual length baseline -> must return None and source="insufficient_data"
    result = predict_next_cycle([], usual_cycle_days=None)
    assert result.predicted_cycle_length is None
    assert result.source == "insufficient_data"
    assert result.confidence == "insufficient_data"

    # 0 cycles, user-supplied usual length 31 -> baseline used with source="usual_cycle"
    result2 = predict_next_cycle([], usual_cycle_days=31)
    assert result2.predicted_cycle_length == 31
    assert result2.source == "usual_cycle"
    assert result2.confidence == "low"


def test_user_baseline_out_of_range_ignored():
    # Out-of-range baseline must NOT be used as prediction (no fake fallback).
    for bad in (None, 10, 19, 46, 90):
        r = predict_next_cycle([], usual_cycle_days=bad)
        assert r.predicted_cycle_length is None
        assert r.source == "insufficient_data"


def test_prediction_weighted_moving_average():
    # Completed cycle lengths: [28, 30, 26]
    # Median=28, MAD=2, no outliers -> WMA (28*1 + 30*2 + 26*3)/6 = 27.67 -> 28
    result = predict_next_cycle([28, 30, 26])
    assert result.predicted_cycle_length == 28
    assert result.source == "history"
    assert result.confidence in ["low", "moderate"]
    assert result.variability_std_dev is not None


# ---------------------------------------------------------------------------
# Phase estimation (Rule H)
# ---------------------------------------------------------------------------
def test_estimate_phase():
    # Bleeding ongoing -> menstrual
    assert estimate_phase(cycle_day=3, cycle_length=28, is_bleeding=True) == "menstrual"
    # Post-bleeding early cycle -> follicular
    assert estimate_phase(cycle_day=8, cycle_length=28, is_bleeding=False) == "follicular"
    # Mid-cycle ovulation window (day 14 +/- 1)
    assert estimate_phase(cycle_day=14, cycle_length=28, is_bleeding=False) == "ovulation"
    # Late cycle -> luteal
    assert estimate_phase(cycle_day=22, cycle_length=28, is_bleeding=False) == "luteal"


def test_estimate_phase_unknown_without_evidence():
    # Rule H: no silent 28-day fallback.
    assert estimate_phase(cycle_day=10, cycle_length=None, is_bleeding=False) == "unknown"
    assert estimate_phase(cycle_day=10, cycle_length=99, is_bleeding=False) == "unknown"
    assert estimate_phase(cycle_day=10, cycle_length=10, is_bleeding=False) == "unknown"
    assert estimate_phase(cycle_day=None, cycle_length=28, is_bleeding=False) == "unknown"
    # Bleeding is directly observed -> still menstrual even without length.
    assert estimate_phase(cycle_day=2, cycle_length=None, is_bleeding=True) == "menstrual"


# ---------------------------------------------------------------------------
# Summary-level behaviour (Rules F, G, I): prediction_status, clamping,
# ongoing precedence, no periods. Uses real service with injected today.
# ---------------------------------------------------------------------------
async def _seed_user(db_session, user_id, periods, usual_cycle=None, usual_period=5):
    profile = Profile(
        user_id=user_id, name="Phase1", usual_cycle_days=usual_cycle,
        usual_period_days=usual_period,
    )
    db_session.add(profile)
    await db_session.flush()
    for start, end in periods:
        db_session.add(Cycle(user_id=user_id, period_start=start, period_end=end))
    await db_session.commit()


@pytest.mark.asyncio
async def test_summary_prediction_upcoming(db_session):
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [
        (date(2026, 7, 1), date(2026, 7, 5)),
        (date(2026, 7, 29), date(2026, 8, 2)),
    ])
    today = date(2026, 8, 10)
    s = await get_current_cycle_summary(db_session, uid, today=today)
    assert s["has_data"] is True
    assert s["predicted_next_period"] is not None
    assert s["days_until_next_period"] is not None
    assert s["days_until_next_period"] > 0
    assert s["prediction_status"] == "upcoming"


@pytest.mark.asyncio
async def test_summary_prediction_today(db_session):
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [
        (date(2026, 6, 1), date(2026, 6, 5)),
        (date(2026, 6, 29), date(2026, 7, 3)),
    ])
    # Jun29 + 28 = Jul27
    today = date(2026, 7, 27)
    s = await get_current_cycle_summary(db_session, uid, today=today)
    assert s["days_until_next_period"] == 0
    assert s["prediction_status"] == "today"


@pytest.mark.asyncio
async def test_summary_prediction_passed_is_neutral_not_negative(db_session):
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [
        (date(2026, 6, 1), date(2026, 6, 5)),
        (date(2026, 6, 29), date(2026, 7, 3)),
    ])
    today = date(2026, 8, 5)  # well past Jul27 prediction
    s = await get_current_cycle_summary(db_session, uid, today=today)
    assert s["days_until_next_period"] == 0, "must be clamped, never negative"
    assert s["days_until_next_period"] >= 0
    assert s["prediction_status"] == "awaiting_next_start"


@pytest.mark.asyncio
async def test_summary_never_negative_across_scenarios(db_session):
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [
        (date(2026, 5, 1), date(2026, 5, 5)),
        (date(2026, 5, 29), date(2026, 6, 2)),
    ])
    for today in [date(2026, 6, 10), date(2026, 6, 26), date(2026, 7, 15), date(2026, 9, 1)]:
        s = await get_current_cycle_summary(db_session, uid, today=today)
        d = s["days_until_next_period"]
        assert d is None or d >= 0, f"negative countdown on {today}: {d}"


@pytest.mark.asyncio
async def test_summary_ongoing_takes_precedence(db_session):
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [
        (date(2026, 6, 1), date(2026, 6, 5)),
        (date(2026, 7, 1), date(2026, 7, 5)),
        (date(2026, 8, 1), None),  # ongoing
    ])
    today = date(2026, 8, 3)
    s = await get_current_cycle_summary(db_session, uid, today=today)
    assert s["is_ongoing"] is True
    assert s["is_bleeding"] is True
    assert s["current_cycle_day"] == 3
    assert s["latest_period_end"] is None


@pytest.mark.asyncio
async def test_summary_completed_period(db_session):
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [
        (date(2026, 7, 1), date(2026, 7, 5)),
    ])
    today = date(2026, 7, 10)
    s = await get_current_cycle_summary(db_session, uid, today=today)
    assert s["is_ongoing"] is False
    assert s["is_bleeding"] is False
    assert s["current_cycle_day"] == 10


@pytest.mark.asyncio
async def test_summary_no_periods(db_session):
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [])
    s = await get_current_cycle_summary(db_session, uid, today=date(2026, 8, 10))
    assert s["has_data"] is False
    assert s["phase"] == "unknown"
    assert s["predicted_next_period"] is None
    assert s["days_until_next_period"] is None
    assert s["prediction_confidence"] == "insufficient_data"


@pytest.mark.asyncio
async def test_summary_future_does_not_train(db_session):
    from app.services.summary import get_current_cycle_summary
    uid_obs = uuid.uuid4()
    uid_fut = uuid.uuid4()
    await _seed_user(db_session, uid_obs, [
        (date(2026, 7, 1), date(2026, 7, 5)),
        (date(2026, 7, 29), date(2026, 8, 2)),
    ])
    await _seed_user(db_session, uid_fut, [
        (date(2026, 7, 1), date(2026, 7, 5)),
        (date(2026, 7, 29), date(2026, 8, 2)),
        (date(2026, 10, 1), date(2026, 10, 5)),  # future display-only
    ])
    today = date(2026, 8, 10)
    s_obs = await get_current_cycle_summary(db_session, uid_obs, today=today)
    s_fut = await get_current_cycle_summary(db_session, uid_fut, today=today)
    assert s_obs["predicted_cycle_length"] == s_fut["predicted_cycle_length"]
    assert s_obs["average_cycle_length"] == s_fut["average_cycle_length"]


@pytest.mark.asyncio
async def test_summary_date_boundary_and_timezone_consistency(db_session):
    """Same instant, date-only semantics: explicit today is the contract (Rule I)."""
    from app.services.summary import get_current_cycle_summary
    uid = uuid.uuid4()
    await _seed_user(db_session, uid, [
        (date(2026, 7, 1), date(2026, 7, 5)),
        (date(2026, 7, 29), date(2026, 8, 2)),
    ])
    s1 = await get_current_cycle_summary(db_session, uid, today=date(2026, 8, 10))
    s2 = await get_current_cycle_summary(db_session, uid, today=date(2026, 8, 10))
    assert s1["current_cycle_day"] == s2["current_cycle_day"] == 13
    assert s1["days_until_next_period"] == s2["days_until_next_period"]
    assert s1["prediction_status"] == s2["prediction_status"]
