import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


# Provenance for this singleton is a fixed response label, not a stored enum:
# the only possible source of the row is the owning user's explicit input
# (mirroring the health-notes "user-provided context" pattern). No other
# value is ever emitted — in particular CLINICALLY_CONFIRMED is never
# emitted for user-typed context.
AGING_PROVENANCE_USER_DECLARED = "user_declared"

AGING_SAFETY_NOTE = (
    "User-controlled reproductive-aging context only. MenoMate does not "
    "diagnose menopause or perimenopause, does not interpret cycle changes "
    "as a diagnosis, and does not infer clinical confirmation from a user's "
    "selection. This context never alters period predictions and never "
    "changes fertility-estimate behavior."
)

AGING_RESPONSE_DISCLAIMER = (
    "Educational context only. Recorded context is what the user chose to "
    "save; it is not a medical diagnosis, not a staging of menopausal "
    "transition, and not a statement about fertility. Cycle-pattern "
    "information remains available through existing cycle and summary "
    "endpoints, unchanged by this context. This information is not a "
    "substitute for clinical care."
)


class AgingContextPut(BaseModel):
    """Full-replacement upsert (PUT): notes is set from the payload and an
    omitted/null value clears the recorded context (deactivation path).
    Creates the singleton row on first sync."""

    notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Free-text reproductive-aging context the user wants saved; stored verbatim, never parsed into medical facts",
    )


class AgingContextResponse(BaseModel):
    user_id: uuid.UUID
    has_context: bool = Field(
        ...,
        description="True when the user has recorded notes; False when never set or cleared",
    )
    notes: Optional[str] = Field(
        default=None,
        description="Verbatim user-recorded context; null when none recorded",
    )
    provenance: str = Field(
        default=AGING_PROVENANCE_USER_DECLARED,
        description="Fixed label 'user_declared': this row can only ever reflect the owning user's explicit input, never a system derivation or clinical confirmation",
    )
    disclaimer: str = Field(default=AGING_RESPONSE_DISCLAIMER)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
