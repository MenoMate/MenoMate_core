"""Phase 2 fertility/ovulation estimation (evidence-gated, server-owned).

Separate capability from the frozen production next-period predictor
(`app/services/cycle_calculator.py`, robust_wma_v1). This module READS
completed cycle history through the existing `calculate_cycle_lengths` /
`predict_next_cycle` interfaces and READS user fertility observations. It
never writes to cycles, the prediction ledger, summaries, or health context,
and it never alters period predictions.

Conceptual pipeline: OBSERVED DATA -> EVIDENCE -> ESTIMATE -> CONFIDENCE.

Evidence character (load-bearing, from the Phase 2 product contract):
- LH `positive` records a test outcome only; it never proves ovulation
  occurred. It is the only prospective surge signal, so it is the only
  biomarker that can anchor a dated estimate — always labeled ESTIMATED.
- BBT is retrospective evidence; it is counted and cited but never drives a
  prospective window on its own.
- Cervical mucus is supportive observation data (dedicated scale, distinct
  from `daily_logs.discharge`); counted and cited, never sufficient alone.

Status gating reuses the frozen period predictor's own outputs and invents
no fertility-specific counts, weights, scores, or probabilities:
- INSUFFICIENT_DATA: zero valid cycle intervals AND zero in-scope biomarker
  observations. Dated fields are null. A stated `usual_cycle_days` is
  deliberately NOT used as a fertility fallback (no silent 28-day default).
- LOW_CONFIDENCE: some evidence exists but a dated estimate is not warranted
  (calendar history without a same-cycle LH anchor, biomarkers without a
  history anchor, or history the reused predictor itself rates `low`).
  Dated fields are null — never fabricated.
- AVAILABLE: history-anchored (`predict_next_cycle` source == "history" with
  reused confidence `moderate`/`high`, i.e. the existing MAD policy, not a
  new fertility threshold) AND at least one same-cycle LH-positive
  observation. Only then are dated estimates emitted.
- SUPPRESSED: explicit pregnancy mode is active (Phase 3). The legacy
  `health_contexts.pregnancy_context` selection keeps its existing
  zero-behavioral-effect semantics and is never reinterpreted, so only the
  new explicit pregnancy-mode flag triggers this state. Dated fields are
  null — never exposed while suppressed.

Dated-estimate parameters (named, versioned estimator constants — Phase 2
product parameters requiring clinical sign-off, not medical facts):
- LUTEAL_ESTIMATE_DAYS = 14 reuses this codebase's existing count-back
  convention (`estimate_phase`: ovulation ~= length - 14) as an ESTIMATED
  anchor with stated uncertainty; individual luteal phases vary, so the
  result is presented as an estimated date inside an estimated window, never
  exact and never confirmed.
- FERTILE_WINDOW_DAYS_BEFORE/AFTER = 5/1 defines the educational estimated
  window around that anchor. It is not a contraceptive schedule: the fixed
  response disclaimer forbids safe/unsafe-day and guarantee language.

Estimates are computed on read (every GET reflects all observed-data changes
— period, LH, BBT, mucus — with no stale cache) and are client read-only.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cycle import Cycle
from app.models.fertility_observation import FertilityObservation
from app.models.profile import Profile
from app.schemas.fertility import FERTILITY_ESTIMATE_DISCLAIMER
from app.services.cycle_calculator import calculate_cycle_lengths, predict_next_cycle
from app.services.timezone import user_today

# Frozen estimator identity (parallels robust_wma_v1 discipline): bump ONLY
# when the estimator logic itself changes.
FERTILITY_METHOD = "fertility_v1"
FERTILITY_METHOD_VERSION = "1.0.0"
EVIDENCE_SCHEMA_VERSION = 1

# Named Phase 2 product parameters (see module docstring). Educational
# estimates pending clinical sign-off — not medical truths.
LUTEAL_ESTIMATE_DAYS = 14
FERTILE_WINDOW_DAYS_BEFORE = 5
FERTILE_WINDOW_DAYS_AFTER = 1

# Closed status + provenance vocabularies (no other values may be emitted).
STATUS_AVAILABLE = "AVAILABLE"
STATUS_LOW_CONFIDENCE = "LOW_CONFIDENCE"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_SUPPRESSED = "SUPPRESSED"
ALLOWED_STATUSES = (
    STATUS_AVAILABLE,
    STATUS_LOW_CONFIDENCE,
    STATUS_INSUFFICIENT_DATA,
    STATUS_SUPPRESSED,
)

EVIDENCE_OBSERVED = "OBSERVED"
EVIDENCE_ESTIMATED = "ESTIMATED"
EVIDENCE_CLINICALLY_CONFIRMED = "CLINICALLY_CONFIRMED"


def _utcnow() -> datetime:
    """Current instant. Sealed seam for tests (mirrors timezone._utcnow)."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FertilityEstimate:
    """Deterministic estimate value object (pure-logic result)."""

    estimate_date: date
    status: str
    estimated_ovulation_date: Optional[date]
    fertile_window_start: Optional[date]
    fertile_window_end: Optional[date]
    evidence_source: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    method: str = FERTILITY_METHOD
    method_version: str = FERTILITY_METHOD_VERSION
    calculated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    timezone_name: str = "UTC"
    disclaimer: str = FERTILITY_ESTIMATE_DISCLAIMER

    def to_response_dict(self) -> Dict[str, Any]:
        return {
            "estimate_date": self.estimate_date,
            "status": self.status,
            "estimated_ovulation_date": self.estimated_ovulation_date,
            "fertile_window_start": self.fertile_window_start,
            "fertile_window_end": self.fertile_window_end,
            "evidence_source": self.evidence_source,
            "evidence": dict(self.evidence),
            "method": self.method,
            "method_version": self.method_version,
            "calculated_at": self.calculated_at,
            "timezone_name": self.timezone_name,
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True)
class ObservationEvidence:
    """Minimal in-memory view of one observation row for pure computation."""

    observation_date: date
    observation_type: str
    lh_result: Optional[str] = None


def compute_fertility_estimate(
    *,
    as_of: date,
    latest_period_start: Optional[date],
    cycle_intervals: List[int],
    predicted_cycle_length: Optional[int],
    period_confidence: str,
    period_source: str,
    variability_mad: Optional[float],
    observations: List[ObservationEvidence],
    timezone_name: str,
    now: Optional[datetime] = None,
) -> FertilityEstimate:
    """Pure deterministic estimator (no I/O; fully testable).

    `observations` must already be filtered to `observation_date <= as_of`
    (the caller enforces the no-future-evidence rule). Only observations on
    or after `latest_period_start` (the current-cycle window) count as
    estimate evidence; older rows are reported in metadata totals but do not
    anchor the current estimate.
    """
    instant = now if now is not None else _utcnow()
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)

    scoped = [
        o
        for o in observations
        if latest_period_start is None or o.observation_date >= latest_period_start
    ]
    lh_positive_dates = sorted(
        o.observation_date
        for o in scoped
        if o.observation_type == "lh_test" and o.lh_result == "positive"
    )
    lh_tests_total = sum(1 for o in scoped if o.observation_type == "lh_test")
    bbt_points = sum(1 for o in scoped if o.observation_type == "bbt")
    mucus_observations = sum(1 for o in scoped if o.observation_type == "cervical_mucus")
    biomarker_types = sorted(
        {o.observation_type for o in scoped if o.observation_type in ("lh_test", "bbt", "cervical_mucus")}
    )

    has_history = period_source == "history" and predicted_cycle_length is not None
    has_any_evidence = len(cycle_intervals) > 0 or len(scoped) > 0
    # A stated usual_cycle_days is deliberately never a fertility fallback: the
    # evidence cites a predicted length only when observed history produced it.
    cited_length = predicted_cycle_length if has_history else None

    evidence: Dict[str, Any] = {
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "cycle_intervals_used": len(cycle_intervals),
        "predicted_cycle_length": cited_length,
        "period_confidence": period_confidence,
        "period_source": period_source,
        "basis_start": latest_period_start.isoformat() if latest_period_start else None,
        "variability_mad": variability_mad,
        "lh_positive_dates": [d.isoformat() for d in lh_positive_dates],
        "lh_tests_total": lh_tests_total,
        "bbt_points": bbt_points,
        "mucus_observations": mucus_observations,
        "biomarker_types_present": biomarker_types,
    }

    if not has_any_evidence:
        return FertilityEstimate(
            estimate_date=as_of,
            status=STATUS_INSUFFICIENT_DATA,
            estimated_ovulation_date=None,
            fertile_window_start=None,
            fertile_window_end=None,
            evidence_source=EVIDENCE_ESTIMATED,
            evidence=evidence,
            calculated_at=instant,
            timezone_name=timezone_name,
        )

    history_stable = has_history and period_confidence in ("moderate", "high")
    if history_stable and latest_period_start is not None and lh_positive_dates:
        predicted_next = latest_period_start + timedelta(days=predicted_cycle_length or 0)
        ovulation = predicted_next - timedelta(days=LUTEAL_ESTIMATE_DAYS)
        window_start = ovulation - timedelta(days=FERTILE_WINDOW_DAYS_BEFORE)
        window_end = ovulation + timedelta(days=FERTILE_WINDOW_DAYS_AFTER)
        return FertilityEstimate(
            estimate_date=as_of,
            status=STATUS_AVAILABLE,
            estimated_ovulation_date=ovulation,
            fertile_window_start=window_start,
            fertile_window_end=window_end,
            evidence_source=EVIDENCE_OBSERVED,
            evidence=evidence,
            calculated_at=instant,
            timezone_name=timezone_name,
        )

    return FertilityEstimate(
        estimate_date=as_of,
        status=STATUS_LOW_CONFIDENCE,
        estimated_ovulation_date=None,
        fertile_window_start=None,
        fertile_window_end=None,
        evidence_source=EVIDENCE_ESTIMATED,
        evidence=evidence,
        calculated_at=instant,
        timezone_name=timezone_name,
    )


async def get_fertility_estimate(
    db: AsyncSession,
    user_id: uuid.UUID,
    as_of: Optional[date] = None,
    now: Optional[datetime] = None,
) -> FertilityEstimate:
    """Server-owned estimate computation for one user (reads only).

    Resolves the user-local as-of date via the canonical timezone service,
    reads cycle history through the frozen predictor interfaces, and scopes
    observations to `observation_date <= as_of`. Raises ValueError when
    `as_of` is in the future relative to the user's local today (routes map
    this to HTTP 400): future biological evidence must never enter the engine.

    Phase 3 contextual layer: when explicit pregnancy mode is active for the
    user, returns the SUPPRESSED state with null dated fields (no ovulation /
    fertile-window / next-period prediction is exposed through this
    pregnancy-aware contract). Historical rows are untouched; the frozen
    period predictor is never modified — this branch only gates what the
    reproductive estimate endpoint presents.
    """
    # Pregnancy-mode gate first: explicit user-controlled context only. The
    # legacy health_contexts.pregnancy_context selection is never consulted
    # here (it keeps zero behavioral effect by design).
    from app.services.pregnancy import is_pregnancy_mode_active

    profile_res = await db.execute(select(Profile).where(Profile.user_id == user_id))
    profile = profile_res.scalar_one_or_none()
    tz_name = profile.timezone if profile and profile.timezone else None
    today = user_today(tz_name, now=now)
    effective = as_of or today
    if effective > today:
        raise ValueError("as_of cannot be in the future")
    # DATEs are compared as dates; never shifted through UTC.
    label = tz_name.strip() if tz_name and tz_name.strip() else "UTC (profile timezone unset)"

    if await is_pregnancy_mode_active(db, user_id):
        instant = now if now is not None else _utcnow()
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=timezone.utc)
        return FertilityEstimate(
            estimate_date=effective,
            status=STATUS_SUPPRESSED,
            estimated_ovulation_date=None,
            fertile_window_start=None,
            fertile_window_end=None,
            evidence_source=EVIDENCE_ESTIMATED,
            evidence={
                "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
                "pregnancy_mode_active": True,
                "suppression_reason": (
                    "Pregnancy mode is active: current ovulation, fertile-window, "
                    "and next-period predictions are withheld from this "
                    "pregnancy-aware response. Historical data is retained."
                ),
            },
            calculated_at=instant,
            timezone_name=label,
        )

    cycles_res = await db.execute(
        select(Cycle)
        .where(Cycle.user_id == user_id)
        .order_by(Cycle.period_start.asc())
    )
    periods: List[Cycle] = list(cycles_res.scalars().all())
    intervals = calculate_cycle_lengths(periods, today=effective)
    usual = profile.usual_cycle_days if profile else None
    prediction = predict_next_cycle(
        completed_cycle_lengths=intervals,
        usual_cycle_days=usual,
    )

    starts = [p.period_start for p in periods if p.period_start <= effective]
    latest_start: Optional[date] = max(starts) if starts else None

    obs_res = await db.execute(
        select(FertilityObservation)
        .where(
            FertilityObservation.user_id == user_id,
            FertilityObservation.observation_date <= effective,
        )
        .order_by(
            FertilityObservation.observation_date.asc(),
            FertilityObservation.id.asc(),
        )
    )
    rows = list(obs_res.scalars().all())
    scoped_input = [
        ObservationEvidence(
            observation_date=r.observation_date,
            observation_type=r.observation_type,
            lh_result=r.lh_result,
        )
        for r in rows
    ]

    return compute_fertility_estimate(
        as_of=effective,
        latest_period_start=latest_start,
        cycle_intervals=intervals,
        predicted_cycle_length=prediction.predicted_cycle_length,
        period_confidence=prediction.confidence,
        period_source=prediction.source,
        variability_mad=prediction.variability_std_dev,
        observations=scoped_input,
        timezone_name=label,
        now=now,
    )
