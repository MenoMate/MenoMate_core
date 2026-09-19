import uuid
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatingSourceEnum(str, Enum):
    """Exact terminology from the Phase 1 design contract (§4.2)."""

    lmp = "lmp"
    ultrasound = "ultrasound"
    clinician = "clinician"
    unknown = "unknown"


PREGNANCY_SAFETY_NOTE = (
    "Pregnancy mode is explicit user-controlled context. It never diagnoses "
    "pregnancy, never infers pregnancy from late periods or model output, and "
    "never overrides clinician-established dating. Estimated dates are "
    "educational estimates, not clinical confirmation."
)

PREGNANCY_RESPONSE_DISCLAIMER = (
    "Educational context only. An estimated due date is an estimate, not a "
    "guarantee of delivery timing and not a medical diagnosis. Only a "
    "clinician-established date carries clinical provenance, and MenoMate "
    "never verifies clinician claims. Gestational age is derived from the "
    "stored dating basis as an estimate. This information is not a substitute "
    "for prenatal care."
)


def _coarse_future_guard(value: Optional[date]) -> Optional[date]:
    # Coarse server-relative guard for clock variance (schema validators run
    # without user context). Routes enforce the exact USER-LOCAL bound
    # (lmp/confirmation <= the user's local today); see api/v1/reproductive.py.
    if value is not None and value > date.today() + timedelta(days=1):
        raise ValueError("date cannot be in the future")
    return value


class PregnancyPut(BaseModel):
    """Full-replacement upsert (PUT): omitted fields are cleared to null,
    except is_active which defaults to True when omitted (activation intent).
    Creates the singleton row on first sync."""

    is_active: bool = Field(
        default=True,
        description="Explicit mode switch. True activates pregnancy mode; False retains history with mode off.",
    )
    dating_source: Optional[DatingSourceEnum] = Field(
        default=None,
        description="Provenance: lmp | ultrasound | clinician | unknown. Required when estimated_due_date is set.",
    )
    estimated_due_date: Optional[date] = Field(
        default=None,
        description="User-local calendar EDD as provided (verbatim store; the server never auto-computes it). Null = unavailable/unknown.",
    )
    lmp_date: Optional[date] = Field(
        default=None,
        description="User-local first day of last menstrual period. Provenance for lmp dating only; never used to auto-compute an EDD.",
    )
    confirmation_date: Optional[date] = Field(
        default=None,
        description="User-local date pregnancy was confirmed (test/clinician). Null if unconfirmed.",
    )
    dating_note: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Verbatim user/clinician note (e.g. 'dating scan 12w'); never parsed into medical facts",
    )

    @field_validator("lmp_date")
    @classmethod
    def check_lmp_coarse(cls, v: Optional[date]) -> Optional[date]:
        return _coarse_future_guard(v)

    @field_validator("confirmation_date")
    @classmethod
    def check_confirmation_coarse(cls, v: Optional[date]) -> Optional[date]:
        return _coarse_future_guard(v)


class PregnancyPatch(BaseModel):
    """Partial update (PATCH): only explicitly included fields are modified.
    Explicitly passing null clears the corresponding optional field."""

    is_active: Optional[bool] = Field(default=None)
    dating_source: Optional[DatingSourceEnum] = Field(default=None)
    estimated_due_date: Optional[date] = Field(default=None)
    lmp_date: Optional[date] = Field(default=None)
    confirmation_date: Optional[date] = Field(default=None)
    dating_note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("lmp_date")
    @classmethod
    def check_lmp_coarse(cls, v: Optional[date]) -> Optional[date]:
        return _coarse_future_guard(v)

    @field_validator("confirmation_date")
    @classmethod
    def check_confirmation_coarse(cls, v: Optional[date]) -> Optional[date]:
        return _coarse_future_guard(v)


class PregnancyResponse(BaseModel):
    user_id: uuid.UUID
    is_active: bool
    dating_source: Optional[str] = None
    estimated_due_date: Optional[date] = None
    lmp_date: Optional[date] = None
    confirmation_date: Optional[date] = None
    dating_note: Optional[str] = None
    # Derived, read-only dating representation (computed from the stored basis
    # + the user's local as-of date; never stored, never a diagnosis).
    edd_status: str = Field(
        ...,
        description="'available' when a valid EDD is stored; 'unavailable' when dating data is absent (never invented)",
    )
    edd_label: str = Field(
        ...,
        description="'clinician_established_due_date' for clinician provenance; 'estimated_due_date' otherwise",
    )
    dating_confidence: str = Field(
        ...,
        description="Provenance tier: CLINICALLY_CONFIRMED (clinician) | ESTIMATED (ultrasound/lmp) | UNKNOWN (unknown/unset)",
    )
    gestational_age_total_days: Optional[int] = Field(
        default=None,
        description="Derived gestational age in days from the dating basis + as-of date; null when unavailable",
    )
    gestational_age_weeks: Optional[int] = Field(default=None)
    gestational_age_days: Optional[int] = Field(
        default=None,
        description="Remainder days within the week (0-6); null when unavailable",
    )
    days_until_due: Optional[int] = Field(
        default=None,
        description="Signed (estimated_due_date - as_of_date).days; null when EDD unavailable. May be negative post-term; mode never auto-exits.",
    )
    as_of_date: date = Field(..., description="User-local date the derivation used")
    timezone_name: str = Field(..., description="IANA zone the as-of date was resolved in")
    disclaimer: str = Field(default=PREGNANCY_RESPONSE_DISCLAIMER)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
