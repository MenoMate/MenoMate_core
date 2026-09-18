import uuid
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


class ReproductiveAgingContext(Base):
    """
    Explicit user-controlled reproductive-aging context (Phase 4, NEW).

    Minimal persistence anchor per the Phase 1 design contract (§4.3, §11):
    a singleton free-text note the user owns, mirroring the health-notes
    pattern. Stored verbatim, never parsed into medical facts.

    Deliberately absent (never add without product/clinical review):
    - no perimenopause_stage / menopause_status / staging enum
    - no menopause/postmenopause diagnosis column
    - no automatic detection fields (no age-derived or variability-derived state)
    - no date fields (no context start date, no LMP/FMP date, no
      clinician-confirmed date — none are defined by the contract)
    - no provenance column (the only possible source for this row is the
      owning user's explicit input; responses carry a fixed
      `provenance = "user_declared"` label instead of a stored enum)

    Behavioral guarantees (enforced by what this table does NOT connect to):
    - never alters period predictions (frozen `robust_wma_v1` untouched)
    - never alters fertility estimates (Phase 2 behavior preserved verbatim)
    - never activates, deactivates, or modifies pregnancy mode (Phase 3
      singleton is fully independent; both may coexist)
    - never deletes historical data (cycles, logs, symptoms, observations,
      pregnancy context, ledger rows are untouched by context changes)

    Grain: zero or one row per user. Absence (or a row with NULL notes) means
    the user has not recorded reproductive-aging context. Clearing is via
    PUT with notes omitted/null (full-replacement semantics); there is no
    PATCH/DELETE surface for this singleton.
    """

    __tablename__ = "reproductive_aging_contexts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user: Mapped["Profile"] = relationship(
        "Profile", back_populates="reproductive_aging_context"
    )
