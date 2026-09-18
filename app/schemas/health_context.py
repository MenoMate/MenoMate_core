from datetime import datetime
from enum import Enum
import uuid
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

# All health-context values are explicitly user-provided context. The backend
# stores them and returns them to the owning client only: it never diagnoses,
# never infers conditions (from symptoms or medications), and never lets
# these values alter prediction calculations.


class ContraceptionMethodEnum(str, Enum):
    none = "none"
    combined_pill = "combined_pill"
    progestin_only_pill = "progestin_only_pill"
    patch = "patch"
    ring = "ring"
    injection = "injection"
    implant = "implant"
    hormonal_iud = "hormonal_iud"
    copper_iud = "copper_iud"
    condoms = "condoms"
    sterilization = "sterilization"
    fertility_awareness = "fertility_awareness"
    withdrawal = "withdrawal"
    other = "other"
    prefer_not_to_say = "prefer_not_to_say"


class PregnancyContextEnum(str, Enum):
    trying_to_conceive = "trying_to_conceive"
    avoiding_pregnancy = "avoiding_pregnancy"
    pregnant = "pregnant"
    postpartum = "postpartum"
    not_applicable = "not_applicable"
    prefer_not_to_say = "prefer_not_to_say"


# Small curated allowlist of structured condition keys. Deliberately NOT an
# exhaustive medical taxonomy; anything else is captured via code "other"
# with the user's own label in custom_label.
SUPPORTED_CONDITION_CODES = frozenset(
    {
        "pcos",
        "endometriosis",
        "uterine_fibroids",
        "thyroid_disorder",
        "anemia",
        "diabetes",
        "hypertension",
        "migraine",
        "anxiety",
        "depression",
        "asthma",
        "other",
    }
)

OTHER_CONDITION_CODE = "other"


def normalize_condition_code(value: str) -> str:
    """Normalize a user-supplied condition key; raises ValueError if unknown."""
    clean = value.strip().lower()
    if clean not in SUPPORTED_CONDITION_CODES:
        raise ValueError(
            f"Unsupported condition_code '{value}'. Supported: {sorted(SUPPORTED_CONDITION_CODES)}"
        )
    return clean


def validate_condition_label(condition_code: str, custom_label: Optional[str]) -> Optional[str]:
    """
    Enforce the 'other'-label contract: custom_label is required (non-blank)
    exactly when condition_code is 'other', and must be absent otherwise.
    Returns the stripped label or None. Raises ValueError on violation.
    """
    if condition_code == OTHER_CONDITION_CODE:
        if custom_label is None or not custom_label.strip():
            raise ValueError("custom_label is required when condition_code is 'other'")
        return custom_label.strip()
    if custom_label is not None:
        raise ValueError("custom_label is only valid when condition_code is 'other'")
    return None


def normalize_medication_name(value: str) -> str:
    """Strip a medication name; raises ValueError when blank."""
    clean = value.strip()
    if not clean:
        raise ValueError("medication name cannot be empty or whitespace only")
    return clean


class HealthContextUpsert(BaseModel):
    """Full-replacement upsert (PUT): omitted fields are cleared to null."""

    contraception_method: Optional[ContraceptionMethodEnum] = None
    contraception_note: Optional[str] = Field(default=None, max_length=1000)
    pregnancy_context: Optional[PregnancyContextEnum] = None
    health_notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Free-text context the user wants MenoMate to know; stored verbatim, never parsed into medical facts",
    )


class HealthContextUpdate(BaseModel):
    """Partial update (PATCH): only explicitly included fields are modified."""

    contraception_method: Optional[ContraceptionMethodEnum] = None
    contraception_note: Optional[str] = Field(default=None, max_length=1000)
    pregnancy_context: Optional[PregnancyContextEnum] = None
    health_notes: Optional[str] = Field(default=None, max_length=2000)


class HealthContextResponse(BaseModel):
    user_id: uuid.UUID
    contraception_method: Optional[str] = None
    contraception_note: Optional[str] = None
    pregnancy_context: Optional[str] = None
    health_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class HealthConditionCreate(BaseModel):
    condition_code: str = Field(
        ...,
        max_length=64,
        description="Structured key from the curated allowlist, or 'other' with custom_label",
    )
    custom_label: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = Field(default=None, max_length=1000)
    is_active: bool = True

    @field_validator("condition_code", mode="before")
    @classmethod
    def normalize_code(cls, v: str) -> str:
        return normalize_condition_code(v)


class HealthConditionUpdate(BaseModel):
    condition_code: Optional[str] = Field(default=None, max_length=64)
    custom_label: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = Field(default=None, max_length=1000)
    is_active: Optional[bool] = None

    @field_validator("condition_code", mode="before")
    @classmethod
    def normalize_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return normalize_condition_code(v)


class HealthConditionResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    condition_code: str
    custom_label: Optional[str] = None
    note: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationCreate(BaseModel):
    name: str = Field(..., max_length=128, description="User-provided medication or treatment name")
    note: Optional[str] = Field(default=None, max_length=1000)
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: str) -> str:
        return normalize_medication_name(v)


class MedicationUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = Field(default=None, max_length=1000)
    is_active: Optional[bool] = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        return normalize_medication_name(v)


class MedicationResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    name: str
    note: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
