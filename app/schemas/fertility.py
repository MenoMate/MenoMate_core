import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ObservationTypeEnum(str, Enum):
    lh_test = "lh_test"
    bbt = "bbt"
    cervical_mucus = "cervical_mucus"


class LHResultEnum(str, Enum):
    positive = "positive"
    negative = "negative"
    invalid = "invalid"


class MucusCategoryEnum(str, Enum):
    dry = "dry"
    sticky = "sticky"
    creamy = "creamy"
    watery = "watery"
    egg_white = "egg_white"


class ObservationSourceEnum(str, Enum):
    manual = "manual"
    imported = "imported"


BBT_MIN_CELSIUS = 35.00
BBT_MAX_CELSIUS = 42.00


def _coarse_future_guard(value: Optional[date]) -> Optional[date]:
    # Coarse server-relative guard for clock variance (schema validators run
    # without user context). Routes enforce the exact USER-LOCAL bound
    # (observation_date <= the user's local today); see api/v1/reproductive.py.
    if value is not None and value > date.today() + timedelta(days=1):
        raise ValueError("observation_date cannot be in the future")
    return value


def _quantize_bbt(value: float) -> float:
    # Preserve NUMERIC(4,2) storage precision: reject nothing here beyond the
    # range check, but round to 2 decimals so stored/returned values agree.
    return round(float(value), 2)


class FertilityObservationCreate(BaseModel):
    """Record one fertility observation (OBSERVED fact, never an estimate)."""

    observation_date: Optional[date] = Field(
        default=None,
        description="User-local calendar date the sample applies to; defaults to the user's local today",
    )
    observation_type: ObservationTypeEnum = Field(
        ..., description="lh_test | bbt | cervical_mucus (closed enum)"
    )
    lh_result: Optional[LHResultEnum] = Field(
        default=None,
        description="LH test result as observed (positive/negative/invalid). Records the test outcome only; never a claim that ovulation occurred.",
    )
    bbt_celsius: Optional[float] = Field(
        default=None,
        ge=BBT_MIN_CELSIUS,
        le=BBT_MAX_CELSIUS,
        description="Measured basal body temperature in Celsius (35.00-42.00, kept to 2 decimals). Stored as measured; never transformed into a conclusion.",
    )
    mucus_category: Optional[MucusCategoryEnum] = Field(
        default=None,
        description="Observed cervical-mucus category (dedicated fertility scale, distinct from daily_logs.discharge)",
    )
    source: ObservationSourceEnum = Field(
        default=ObservationSourceEnum.manual,
        description="manual | imported",
    )
    note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("observation_date")
    @classmethod
    def check_date_coarse(cls, v: Optional[date]) -> Optional[date]:
        return _coarse_future_guard(v)

    @field_validator("bbt_celsius")
    @classmethod
    def quantize_bbt(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return _quantize_bbt(v)

    @model_validator(mode="after")
    def check_exactly_one_value(self) -> "FertilityObservationCreate":
        # Exactly the value column matching observation_type must be set.
        kind = self.observation_type
        has_lh = self.lh_result is not None
        has_bbt = self.bbt_celsius is not None
        has_mucus = self.mucus_category is not None
        if kind == ObservationTypeEnum.lh_test and not (has_lh and not has_bbt and not has_mucus):
            raise ValueError("lh_test observations require lh_result only")
        if kind == ObservationTypeEnum.bbt and not (has_bbt and not has_lh and not has_mucus):
            raise ValueError("bbt observations require bbt_celsius only")
        if kind == ObservationTypeEnum.cervical_mucus and not (
            has_mucus and not has_lh and not has_bbt
        ):
            raise ValueError("cervical_mucus observations require mucus_category only")
        return self


class FertilityObservationUpdate(BaseModel):
    """Partial correction of an observation. observation_type is immutable."""

    observation_date: Optional[date] = Field(default=None)
    lh_result: Optional[LHResultEnum] = Field(default=None)
    bbt_celsius: Optional[float] = Field(default=None, ge=BBT_MIN_CELSIUS, le=BBT_MAX_CELSIUS)
    mucus_category: Optional[MucusCategoryEnum] = Field(default=None)
    source: Optional[ObservationSourceEnum] = Field(default=None)
    note: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("observation_date")
    @classmethod
    def check_date_coarse(cls, v: Optional[date]) -> Optional[date]:
        return _coarse_future_guard(v)

    @field_validator("bbt_celsius")
    @classmethod
    def quantize_bbt(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        return _quantize_bbt(v)


class FertilityObservationResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    observation_date: date
    observation_type: str
    lh_result: Optional[str] = None
    bbt_celsius: Optional[float] = None
    mucus_category: Optional[str] = None
    recorded_at: datetime
    source: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("bbt_celsius", mode="before")
    @classmethod
    def coerce_decimal(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, Decimal):
            return float(v)
        return v

    model_config = ConfigDict(from_attributes=True)


# --- Fertility estimate output (server-computed, client read-only) ---


class FertilityEstimateStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SUPPRESSED = "SUPPRESSED"


class FertilityEvidenceSource(str, Enum):
    OBSERVED = "OBSERVED"
    ESTIMATED = "ESTIMATED"
    CLINICALLY_CONFIRMED = "CLINICALLY_CONFIRMED"


FERTILITY_ESTIMATE_DISCLAIMER = (
    "Educational estimate only. Estimated ovulation and the estimated fertile "
    "window are not guarantees of fertility or infertility, are not "
    "contraception and do not prevent pregnancy, and are not a medical "
    "diagnosis. An LH result records a test observation and does not confirm "
    "that ovulation occurred; BBT is retrospective and does not predict "
    "ovulation."
)


class FertilityEstimateResponse(BaseModel):
    estimate_date: date = Field(
        ..., description="User-local as-of date this estimate was calculated for"
    )
    status: str = Field(
        ...,
        description="AVAILABLE | LOW_CONFIDENCE | INSUFFICIENT_DATA | SUPPRESSED",
    )
    estimated_ovulation_date: Optional[date] = Field(
        default=None,
        description="Estimated ovulation date (educational estimate, not a confirmed fact). Null unless status is AVAILABLE.",
    )
    fertile_window_start: Optional[date] = Field(
        default=None,
        description="Estimated fertile window start, inclusive (educational estimate). Null unless status is AVAILABLE.",
    )
    fertile_window_end: Optional[date] = Field(
        default=None,
        description="Estimated fertile window end, inclusive (educational estimate). Null unless status is AVAILABLE.",
    )
    evidence_source: str = Field(
        ...,
        description="Dominant provenance: OBSERVED (same-cycle biomarker anchors the estimate) | ESTIMATED (calendar inference) | CLINICALLY_CONFIRMED (clinician-established; never emitted in Phase 2)",
    )
    evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Compact evidence metadata: cycle intervals used, biomarker counts, basis start, variability (MAD), schema version",
    )
    method: str = Field(..., description="Estimator identity, e.g. fertility_v1")
    method_version: str = Field(..., description="Estimator version, e.g. 1.0.0")
    calculated_at: datetime = Field(..., description="Instant the estimate was calculated")
    timezone_name: str = Field(
        ..., description="IANA zone the as-of date was resolved in (audit for DST boundaries)"
    )
    disclaimer: str = Field(
        default=FERTILITY_ESTIMATE_DISCLAIMER,
        description="Fixed safety wording: estimates are not guarantees and not contraception",
    )

    model_config = ConfigDict(from_attributes=True)


class FertilityObservationListResponse(BaseModel):
    observations: List[FertilityObservationResponse]
