from datetime import date
from typing import List, NamedTuple, Optional
from app.models.cycle import Cycle


class CyclePrediction(NamedTuple):
    predicted_cycle_length: Optional[int]
    confidence: str
    variability_std_dev: Optional[float]
    source: str


def calculate_period_length(cycle: Cycle) -> Optional[int]:
    """
    Period length = period_end - period_start + 1 when ended.
    """
    if cycle.period_start and cycle.period_end:
        length = (cycle.period_end - cycle.period_start).days + 1
        return max(1, length)
    return None


def _median(values: List[float]) -> float:
    """Return median of a non-empty list."""
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def _mad(values: List[int], med: float) -> float:
    """Median Absolute Deviation: median(|x - median|). Robust variability."""
    if not values:
        return 0.0
    deviations = sorted([abs(float(v) - med) for v in values])
    n = len(deviations)
    mid = n // 2
    if n % 2 == 1:
        return float(deviations[mid])
    return (deviations[mid - 1] + deviations[mid]) / 2.0


def calculate_cycle_lengths(
    periods: List[Cycle],
    today: Optional[date] = None,
) -> List[int]:
    """
    Given periods sorted by period_start ascending:
    cycle_length = current_period_start - previous_period_start.
    Returns list of cycle lengths in days (from oldest to newest).

    Rule B (Phase 1): only OBSERVED period starts (period_start <= today)
    may participate in prediction training. Future/user-entered dates are
    excluded. If today is None, defaults to date.today() so production
    callers are safe by default; tests should pass an explicit today for
    deterministic behaviour.

    Date-only semantics: comparison is on date objects, no datetimes.
    """
    if today is None:
        today = date.today()
    sorted_periods = sorted(periods, key=lambda p: p.period_start)
    # Filter to observed periods only for training.
    observed = [p for p in sorted_periods if p.period_start <= today]
    cycle_lengths: List[int] = []

    for i in range(len(observed) - 1):
        delta = (observed[i + 1].period_start - observed[i].period_start).days
        # Sanity filter: typical biological cycles range between 15 and 90 days
        if 15 <= delta <= 90:
            cycle_lengths.append(delta)

    return cycle_lengths


def predict_next_cycle(
    completed_cycle_lengths: List[int],
    usual_cycle_days: Optional[int] = None,
) -> CyclePrediction:
    """
    Predicts next cycle length using a transparent robust recent-history
    approach (Phase 1, Rule C).

    - Uses up to the 6 most recent VALID observed intervals.
    - Computes median and Median Absolute Deviation (MAD) as robust
      variability (not ordinary std dev).
    - Excludes outliers with |x - median| > 2*MAD before averaging.
      If MAD == 0, only values equal to the median are kept (identical
      history stays identical; single extreme values are dropped).
      If filtering would remove everything, falls back to the median.
    - Computes a recency-weighted mean over the retained values
      (weights 1..m, oldest=1, newest=m) and rounds to int.
    - Clamps result to 20-45 days.

    Returns CyclePrediction(predicted_cycle_length, confidence, variability_std_dev, source).
    NOTE: variability_std_dev field carries the robust MAD value (days) for
    API compatibility; it is a robust variability metric, not ordinary std dev.
    - If sufficient history: source="history".
    - If 0 history but user set a baseline: uses usual_cycle_days (source="usual_cycle", confidence="low").
    - If 0 history and no baseline: returns predicted_cycle_length=None, source="insufficient_data".
      Does not return an arbitrary 28-day estimate as personalized prediction (Rule D).

    Confidence policy (Rule E, conservative, MAD-based):
    - 0 intervals: "insufficient_data" (handled via source above; confidence="insufficient_data")
    - 1-2 intervals: "low"
    - 3-4 intervals: "moderate" only if MAD <= 4.0, else "low"
    - 5-6 intervals: "high" only if MAD <= 3.0; else "moderate" if MAD <= 6.0; else "low"
    Thresholds are documented here and covered by tests.
    """
    if not completed_cycle_lengths:
        if usual_cycle_days and 20 <= usual_cycle_days <= 45:
            return CyclePrediction(
                predicted_cycle_length=usual_cycle_days,
                confidence="low",
                variability_std_dev=None,
                source="usual_cycle",
            )
        return CyclePrediction(
            predicted_cycle_length=None,
            confidence="insufficient_data",
            variability_std_dev=None,
            source="insufficient_data",
        )

    # Use up to the 6 most recent completed cycles (most recent last)
    recent = completed_cycle_lengths[-6:]
    n = len(recent)

    # Robust center + variability (MAD)
    med = _median([float(v) for v in recent])
    mad = _mad(recent, med)
    mad_rounded = round(float(mad), 1)

    # Outlier exclusion: |x - median] > 2*MAD
    if mad == 0:
        filtered = [v for v in recent if float(v) == med]
        if not filtered:
            filtered = [int(round(med))]
    else:
        threshold = 2 * mad
        filtered = [v for v in recent if abs(float(v) - med) <= threshold]
        if not filtered:
            filtered = [int(round(med))]

    # Recency-weighted mean over retained values (oldest=1 ... newest=m)
    m = len(filtered)
    weights = list(range(1, m + 1))
    weighted_sum = sum(w * val for w, val in zip(weights, filtered))
    total_weights = sum(weights)
    predicted_length = round(weighted_sum / total_weights)
    # Clamp to biological boundaries (20 - 45 days)
    predicted_length = max(20, min(45, predicted_length))

    # Determine confidence level (conservative, evidence-based)
    if n <= 2:
        confidence = "low"
    elif 3 <= n <= 4:
        confidence = "moderate" if mad <= 4.0 else "low"
    else:  # 5-6 intervals
        if mad <= 3.0:
            confidence = "high"
        elif mad <= 6.0:
            confidence = "moderate"
        else:
            confidence = "low"

    return CyclePrediction(
        predicted_cycle_length=predicted_length,
        confidence=confidence,
        variability_std_dev=mad_rounded,
        source="history",
    )


def estimate_phase(
    cycle_day: Optional[int],
    cycle_length: Optional[int],
    is_bleeding: bool,
    period_length: int = 5,
) -> str:
    """
    Approximates standard menstrual cycle phase (estimate, not clinical).
    Phases: menstrual, follicular, ovulation, luteal, unknown.

    Rule H (Phase 1): no silent 28-day fallback. When cycle_length is None
    or outside 20-45 and the user is not bleeding, returns "unknown".
    Bleeding always maps to "menstrual" (directly observed). If cycle_day
    is None, returns "unknown".
    Otherwise uses the existing count-back approach (ovulation ≈ length-14).
    """
    if cycle_day is None:
        return "unknown"
    if is_bleeding or cycle_day <= period_length:
        return "menstrual"

    if cycle_length is None or not (20 <= cycle_length <= 45):
        return "unknown"
    effective_length = cycle_length
    ovulation_day = max(period_length + 2, effective_length - 14)

    if cycle_day < ovulation_day - 1:
        return "follicular"
    elif ovulation_day - 1 <= cycle_day <= ovulation_day + 1:
        return "ovulation"
    else:
        return "luteal"
