"""
Phase 3 chronological walk-forward backtesting harness. Evaluation only.

Contract (leakage-proof by construction):
- Input is a user's period starts in strictly ascending order (else ValueError).
- To score target `starts[k]`, the predictor sees ONLY `starts[:k]` plus an
  optional constant `usual` baseline. Future starts are never visible.
- Intervals are derived with the production rule (consecutive start-to-start
  deltas filtered to 15-90 days; see `calculate_cycle_lengths` Rule B). Past
  starts are all <= as_of by construction, so the observed-only filter holds.

Predictors are plain functions `(intervals, usual) -> predicted_length|None`
returning None when they decline to predict (e.g. insufficient history).
`baseline_predict` adapts the frozen production predictor by IMPORT (never a
copy), so the baseline is production behavior by construction.

Production code, schemas, responses, and Flutter are untouched by this module.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, List, Optional

from app.services.cycle_calculator import predict_next_cycle
from app.services.prediction_ledger import BASELINE_METHOD

# Predictor signature: observed intervals (oldest..newest) + optional usual
# baseline -> predicted next cycle length in days, or None (no prediction).
PredictorFn = Callable[[List[int], Optional[int]], Optional[int]]

# Sanity bounds mirrored from calculate_cycle_lengths (15-90 day filter).
MIN_INTERVAL = 15
MAX_INTERVAL = 90


def production_intervals(past_starts: List[date]) -> List[int]:
    """
    Derive observed cycle intervals from consecutive period starts, oldest
    to newest, applying the production 15-90 day sanity filter. All inputs
    must already be <= the prediction as-of date (enforced by walk_forward).
    """
    intervals: List[int] = []
    for prev, cur in zip(past_starts, past_starts[1:]):
        delta = (cur - prev).days
        if MIN_INTERVAL <= delta <= MAX_INTERVAL:
            intervals.append(delta)
    return intervals


def baseline_predict(
    intervals: List[int],
    usual: Optional[int] = None,
) -> Optional[int]:
    """
    Frozen production predictor as a harness predictor. Imports (not copies)
    `predict_next_cycle`, so this baseline IS current production behavior.
    """
    return predict_next_cycle(
        intervals, usual_cycle_days=usual
    ).predicted_cycle_length


@dataclass(frozen=True)
class BacktestPoint:
    """One scored prediction: what was knowable at as_of vs what happened."""

    target_index: int
    as_of: date  # last start visible to the predictor (= anchor_start)
    anchor_start: date  # period start the prediction is counted from
    n_intervals: int  # observed intervals available at as_of
    predicted_length: Optional[int]
    predicted_date: Optional[date]
    target_start: date  # actual next start (ground truth)
    error_days: Optional[int]  # signed: (actual - predicted); None if unpredicted


@dataclass(frozen=True)
class BacktestMetrics:
    n_total: int  # scorable targets
    n_predicted: int  # targets the predictor did not decline
    mae: Optional[float]  # mean |error| over predicted, None if none predicted
    bias: Optional[float]  # mean signed error over predicted
    within_1: Optional[float]  # fraction with |error| <= 1
    within_2: Optional[float]  # fraction with |error| <= 2


def walk_forward(
    starts: List[date],
    predict_fn: PredictorFn,
    usual: Optional[int] = None,
) -> List[BacktestPoint]:
    """
    Score `predict_fn` against each start in `starts[1:]`, using only the
    starts strictly before each target. Returns one point per target.
    """
    if any(b <= a for a, b in zip(starts, starts[1:])):
        raise ValueError("starts must be in strictly ascending order")
    points: List[BacktestPoint] = []
    for k in range(1, len(starts)):
        past = starts[:k]
        anchor = past[-1]
        intervals = production_intervals(past)
        predicted = predict_fn(list(intervals), usual)
        predicted_date = anchor + timedelta(days=predicted) if predicted is not None else None
        target = starts[k]
        error = (target - predicted_date).days if predicted_date is not None else None
        points.append(
            BacktestPoint(
                target_index=k,
                as_of=anchor,
                anchor_start=anchor,
                n_intervals=len(intervals),
                predicted_length=predicted,
                predicted_date=predicted_date,
                target_start=target,
                error_days=error,
            )
        )
    return points


def summarize(points: List[BacktestPoint]) -> BacktestMetrics:
    """Aggregate error metrics over predicted points (unpredicted excluded)."""
    errors = [p.error_days for p in points if p.error_days is not None]
    if not errors:
        return BacktestMetrics(
            n_total=len(points),
            n_predicted=0,
            mae=None,
            bias=None,
            within_1=None,
            within_2=None,
        )
    n = len(errors)
    return BacktestMetrics(
        n_total=len(points),
        n_predicted=n,
        mae=sum(abs(e) for e in errors) / n,
        bias=sum(errors) / n,
        within_1=sum(1 for e in errors if abs(e) <= 1) / n,
        within_2=sum(1 for e in errors if abs(e) <= 2) / n,
    )


def baseline_method() -> str:
    """Ledger/harness label identifying the frozen production baseline."""
    return BASELINE_METHOD
