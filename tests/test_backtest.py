"""
Harness validation with seeded synthetic data (deterministic, no DB).

Proves: chronological scoring matches direct production calls, future data
cannot leak into earlier points, declines are handled, interval derivation
mirrors production, and metrics math is exact.
"""
import random
from datetime import date, timedelta

import pytest

from app.services.backtest import (
    BacktestPoint,
    baseline_predict,
    production_intervals,
    summarize,
    walk_forward,
)
from app.services.cycle_calculator import (
    calculate_cycle_lengths,
    predict_next_cycle,
)
from app.models.cycle import Cycle


def make_series(seed: int, n: int = 12, base: int = 28, jitter: int = 3):
    """Seeded synthetic period starts: regular base + bounded jitter."""
    rng = random.Random(seed)
    starts = [date(2025, 1, 1)]
    for _ in range(n - 1):
        starts.append(starts[-1] + timedelta(days=base + rng.randint(-jitter, jitter)))
    return starts


def test_constant_series_scores_zero_error():
    starts = [date(2025, 1, 1) + timedelta(days=28 * i) for i in range(8)]
    points = walk_forward(starts, baseline_predict)
    assert len(points) == 7
    # First point has no history: production declines (no usual given).
    assert points[0].predicted_length is None
    assert points[0].error_days is None
    for p in points[1:]:
        assert p.error_days == 0
    m = summarize(points)
    assert m.n_total == 7
    assert m.n_predicted == 6
    assert m.mae == 0
    assert m.bias == 0
    assert m.within_1 == 1.0
    assert m.within_2 == 1.0


def test_seeded_series_matches_direct_production_calls():
    """Harness plumbing cross-checked against direct predictor calls."""
    starts = make_series(seed=7, n=14)
    points = walk_forward(starts, baseline_predict, usual=28)
    assert len(points) == 13
    for k, p in enumerate(points, start=1):
        past = starts[:k]
        intervals = [(b - a).days for a, b in zip(past, past[1:])]
        intervals = [d for d in intervals if 15 <= d <= 90]
        expected = predict_next_cycle(intervals, usual_cycle_days=28).predicted_cycle_length
        assert p.n_intervals == len(intervals)
        assert p.predicted_length == expected
        assert p.as_of == past[-1] == p.anchor_start
        assert p.target_start == starts[k]
        if expected is None:
            assert p.error_days is None
        else:
            assert p.predicted_date == past[-1] + timedelta(days=expected)
            assert p.error_days == (starts[k] - p.predicted_date).days
    # Deterministic: identical rerun.
    rerun = walk_forward(starts, baseline_predict, usual=28)
    assert rerun == points


def test_truncation_invariance_no_leakage():
    """Appending future starts must not change earlier scored points."""
    full = make_series(seed=42, n=16)
    full_points = walk_forward(full, baseline_predict, usual=28)
    for m in (4, 8, 12):
        partial_points = walk_forward(full[:m], baseline_predict, usual=28)
        assert partial_points == full_points[: m - 1]


def test_decline_handling_and_metrics():
    assert walk_forward([date(2025, 3, 1)], baseline_predict) == []
    points = walk_forward(
        [date(2025, 3, 1), date(2025, 3, 29)], baseline_predict
    )
    assert len(points) == 1
    assert points[0].n_intervals == 0
    assert points[0].predicted_length is None
    m = summarize(points)
    assert (m.n_total, m.n_predicted) == (1, 0)
    assert m.mae is None and m.bias is None
    assert m.within_1 is None and m.within_2 is None


def test_intervals_mirror_production_rule():
    """Local derivation == production calculate_cycle_lengths (incl. filter)."""
    starts = make_series(seed=99, n=10)
    # Inject a skip-like 120-day gap while preserving ascending order
    # (shift this and all later starts forward).
    gap_at, gap_days = 5, 92  # 28 + 92 = 120-day interval, filtered by production
    starts = [
        s + timedelta(days=gap_days) if i >= gap_at else s
        for i, s in enumerate(starts)
    ]
    for k in range(2, len(starts)):
        past = starts[:k]
        stubs = [Cycle(period_start=s) for s in past]
        assert production_intervals(past) == calculate_cycle_lengths(
            stubs, today=past[-1]
        )


def test_baseline_adapter_is_production():
    intervals = [28, 30, 27, 29, 31]
    assert baseline_predict(intervals, None) == predict_next_cycle(
        intervals
    ).predicted_cycle_length
    assert baseline_predict([], 30) == 30  # usual fallback path
    assert baseline_predict([], None) is None  # insufficient-data path


def test_rejects_unordered_input():
    with pytest.raises(ValueError):
        walk_forward([date(2025, 1, 10), date(2025, 1, 1)], baseline_predict)
    with pytest.raises(ValueError):
        walk_forward([date(2025, 1, 1), date(2025, 1, 1)], baseline_predict)


def test_summarize_math_exact():
    points = [
        BacktestPoint(1, date(2025, 2, 1), date(2025, 2, 1), 1, 28,
                      date(2025, 3, 1), date(2025, 3, 1), 0),
        BacktestPoint(2, date(2025, 3, 1), date(2025, 3, 1), 2, 28,
                      date(2025, 3, 29), date(2025, 3, 30), 1),
        BacktestPoint(3, date(2025, 3, 30), date(2025, 3, 30), 3, 28,
                      date(2025, 4, 27), date(2025, 4, 24), -3),
        BacktestPoint(4, date(2025, 4, 24), date(2025, 4, 24), 0, None,
                      None, date(2025, 5, 22), None),
    ]
    m = summarize(points)
    assert m.n_total == 4
    assert m.n_predicted == 3
    assert m.mae == pytest.approx(4 / 3)
    assert m.bias == pytest.approx(-2 / 3)
    assert m.within_1 == pytest.approx(2 / 3)
    assert m.within_2 == pytest.approx(2 / 3)
