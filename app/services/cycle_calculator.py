from datetime import date, timedelta
import math
from typing import List, NamedTuple, Optional, Tuple
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


def calculate_cycle_lengths(periods: List[Cycle]) -> List[int]:
    """
    Given periods sorted by period_start ascending:
    cycle_length = current_period_start - previous_period_start.
    Returns list of cycle lengths in days (from oldest to newest).
    """
    sorted_periods = sorted(periods, key=lambda p: p.period_start)
    cycle_lengths: List[int] = []
    
    for i in range(len(sorted_periods) - 1):
        delta = (sorted_periods[i + 1].period_start - sorted_periods[i].period_start).days
        # Sanity filter: typical biological cycles range between 15 and 90 days
        if 15 <= delta <= 90:
            cycle_lengths.append(delta)
            
    return cycle_lengths


def predict_next_cycle(
    completed_cycle_lengths: List[int],
    usual_cycle_days: Optional[int] = None,
) -> CyclePrediction:
    """
    Predicts next cycle length using a transparent Weighted Moving Average (WMA)
    over recent completed cycles (inspired by Mētra/Mensinator principles).
    
    Returns CyclePrediction(predicted_cycle_length, confidence, variability_std_dev, source).
    - If sufficient history: calculates WMA from recent cycles (source="history").
    - If 0 history but user set a baseline: uses usual_cycle_days (source="usual_cycle", confidence="low").
    - If 0 history and no baseline: returns predicted_cycle_length=None, source="insufficient_data".
      Does not return an arbitrary 28-day estimate as personalized prediction.
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

    # Weights proportional to recency: 1, 2, ..., n
    weights = list(range(1, n + 1))
    weighted_sum = sum(w * val for w, val in zip(weights, recent))
    total_weights = sum(weights)
    predicted_length = round(weighted_sum / total_weights)
    # Clamp to biological boundaries (20 - 45 days)
    predicted_length = max(20, min(45, predicted_length))

    # Calculate standard deviation
    if n > 1:
        mean = sum(recent) / n
        variance = sum((x - mean) ** 2 for x in recent) / (n - 1)
        std_dev = round(math.sqrt(variance), 1)
    else:
        std_dev = 0.0

    # Determine confidence level
    if n >= 3:
        if std_dev <= 3.5:
            confidence = "high"
        elif std_dev <= 7.0:
            confidence = "moderate"
        else:
            confidence = "low"
    elif n >= 1:
        confidence = "moderate"
    else:
        confidence = "low"

    return CyclePrediction(
        predicted_cycle_length=predicted_length,
        confidence=confidence,
        variability_std_dev=std_dev,
        source="history",
    )


def estimate_phase(
    cycle_day: int,
    cycle_length: Optional[int],
    is_bleeding: bool,
    period_length: int = 5,
) -> str:
    """
    Approximates standard menstrual cycle phase.
    Clearly represented as an estimate rather than a clinical measurement.
    Phases: menstrual, follicular, ovulation, luteal.
    """
    if is_bleeding or cycle_day <= period_length:
        return "menstrual"

    effective_length = cycle_length if (cycle_length and 20 <= cycle_length <= 45) else 28
    ovulation_day = max(period_length + 2, effective_length - 14)

    if cycle_day < ovulation_day - 1:
        return "follicular"
    elif ovulation_day - 1 <= cycle_day <= ovulation_day + 1:
        return "ovulation"
    else:
        return "luteal"
