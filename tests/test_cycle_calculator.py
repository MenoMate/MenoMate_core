from datetime import date
import uuid
import pytest
from app.models.cycle import Cycle
from app.services.cycle_calculator import (
    calculate_cycle_lengths,
    calculate_period_length,
    estimate_phase,
    predict_next_cycle,
)


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

    lengths = calculate_cycle_lengths([p1, p2, p3])
    assert len(lengths) == 2
    assert lengths[0] == 29  # Aug 10 to Sep 8 = 29 days
    assert lengths[1] == 28  # Sep 8 to Oct 6 = 28 days


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


def test_prediction_weighted_moving_average():
    # Completed cycle lengths: [28, 30, 26]
    # Weights: 1, 2, 3 -> (28*1 + 30*2 + 26*3) / 6 = (28 + 60 + 78) / 6 = 166 / 6 = 27.67 -> 28
    result = predict_next_cycle([28, 30, 26])
    assert result.predicted_cycle_length == 28
    assert result.source == "history"
    assert result.confidence in ["high", "moderate"]
    assert result.variability_std_dev is not None


def test_estimate_phase():
    # Bleeding ongoing -> menstrual
    assert estimate_phase(cycle_day=3, cycle_length=28, is_bleeding=True) == "menstrual"
    # Post-bleeding early cycle -> follicular
    assert estimate_phase(cycle_day=8, cycle_length=28, is_bleeding=False) == "follicular"
    # Mid-cycle ovulation window (day 14 +/- 1)
    assert estimate_phase(cycle_day=14, cycle_length=28, is_bleeding=False) == "ovulation"
    # Late cycle -> luteal
    assert estimate_phase(cycle_day=22, cycle_length=28, is_bleeding=False) == "luteal"
