"""Phase 3 pregnancy dating logic (pure, deterministic, no I/O).

Derivation rules (explicit product parameters pending clinical sign-off,
mirroring the Phase 2 LUTEAL_ESTIMATE_DAYS precedent):

- The server NEVER auto-computes an EDD from an LMP date (Phase 1 §8.5:
  "the server does not recompute EDDs"). EDDs are stored verbatim.
- Gestational age prefers a direct calendar subtraction when `lmp_date` is
  known: `as_of - lmp_date` (no gestation-length assumption).
- When only an EDD is known, gestational age uses the standard 40-week
  (280-day, Naegele-convention) reference: `280 - (edd - as_of)`. This is a
  named estimate constant, not a clinical guarantee.
- Dating provenance tiers: clinician -> CLINICALLY_CONFIRMED;
  ultrasound / lmp -> ESTIMATED; unknown / unset -> UNKNOWN.
- Precedence for conflict protection: clinician (3) > ultrasound (2) >
  lmp (1) > unknown (0) > unset/None (-1). A lower-precedence write carrying
  a DIFFERING EDD must not silently replace a higher-precedence stored EDD
  (service layer maps this to HTTP 409).
"""

from datetime import date
from typing import Optional

# Standard 40-week reference (Naegele convention). Estimate parameter pending
# clinical sign-off — not a medical guarantee.
PREGNANCY_GESTATION_DAYS = 280

DATING_PRECEDENCE = {
    "clinician": 3,
    "ultrasound": 2,
    "lmp": 1,
    "unknown": 0,
}

CONFIDENCE_CLINICALLY_CONFIRMED = "CLINICALLY_CONFIRMED"
CONFIDENCE_ESTIMATED = "ESTIMATED"
CONFIDENCE_UNKNOWN = "UNKNOWN"


def precedence_of(source: Optional[str]) -> int:
    """Numeric precedence tier; None (unset) ranks below 'unknown'."""
    if source is None:
        return -1
    return DATING_PRECEDENCE.get(source, -1)


def dating_confidence_for(source: Optional[str]) -> str:
    """Provenance tier label for a dating source."""
    if source == "clinician":
        return CONFIDENCE_CLINICALLY_CONFIRMED
    if source in ("ultrasound", "lmp"):
        return CONFIDENCE_ESTIMATED
    return CONFIDENCE_UNKNOWN


def edd_label_for(source: Optional[str]) -> str:
    """Display label: only clinician provenance avoids the 'estimated' word."""
    if source == "clinician":
        return "clinician_established_due_date"
    return "estimated_due_date"


def compute_gestational_age_total_days(
    *,
    estimated_due_date: Optional[date],
    lmp_date: Optional[date],
    as_of: date,
) -> Optional[int]:
    """Derived gestational age in days, or None when unavailable.

    Prefers direct LMP subtraction (no gestation assumption). Falls back to
    the 280-day EDD reference. Negative EDD-implied ages (EDD more than 40
    weeks out — inconsistent input the API accepts verbatim) clamp to 0
    rather than surfacing a nonsensical negative age. No upper cap: post-term
    continuation past the EDD is valid and never auto-exits pregnancy mode.
    """
    if lmp_date is not None:
        return max(0, (as_of - lmp_date).days)
    if estimated_due_date is not None:
        return max(0, PREGNANCY_GESTATION_DAYS - (estimated_due_date - as_of).days)
    return None


def split_weeks_days(total_days: Optional[int]) -> tuple[Optional[int], Optional[int]]:
    """Split a day count into (weeks, remainder days 0-6); (None, None) when null."""
    if total_days is None:
        return None, None
    return total_days // 7, total_days % 7


def is_downgrade_conflict(
    *,
    existing_source: Optional[str],
    existing_edd: Optional[date],
    incoming_source: Optional[str],
    incoming_edd: Optional[date],
) -> bool:
    """True when a lower-precedence write would silently replace a
    higher-precedence stored EDD with a DIFFERING date.

    Same-date provenance moves, upgrades, first-time dating, clearing, and
    writes while no EDD is stored are never conflicts — only a differing
    lower-provenance EDD over a higher-provenance EDD is rejected. Callers
    map True to HTTP 409 with hierarchy guidance.
    """
    if existing_edd is None or incoming_edd is None:
        return False
    if existing_edd == incoming_edd:
        return False
    return precedence_of(incoming_source) < precedence_of(existing_source)
