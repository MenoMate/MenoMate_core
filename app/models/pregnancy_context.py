import uuid
from datetime import date, datetime, timezone
from typing import Optional, TYPE_CHECKING
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.profile import Profile


# Dating-source vocabulary: exact terminology from the Phase 1 design contract
# (§4.2): lmp | ultrasound | clinician | unknown. Narrow by design — no
# invented clinical fields (no CRL, no gestational-age-at-scan, no provider
# identifiers). Precedence (Phase 3 product hierarchy): clinician (3) >
# ultrasound (2) > lmp (1) > unknown (0). Higher provenance must never be
# silently overwritten by a lower-provenance calculation or write with a
# differing EDD (enforced at the service layer with HTTP 409; see
# app/services/pregnancy.py).
DATING_SOURCES = ("lmp", "ultrasound", "clinician", "unknown")

# Standard obstetric convention used ONLY to derive gestational age from a
# stored EDD when no LMP date is available. Named product parameter pending
# clinical sign-off (mirrors the Phase 2 LUTEAL_ESTIMATE_DAYS precedent):
# 40 weeks = 280 days from LMP to EDD (Naegele convention). The server never
# auto-computes an EDD from an LMP date (per Phase 1 §8.5 "server does not
# recompute EDDs"); EDDs are stored verbatim as provided by the user/clinician
# flow. This constant is used read-only for gestational-age display.
PREGNANCY_GESTATION_DAYS = 280


class PregnancyContext(Base):
    """
    Explicit user-controlled pregnancy mode (Phase 3, NEW).

    Distinct from the legacy free-selection
    `health_contexts.pregnancy_context` (which keeps its existing
    zero-behavioral-effect semantics and is never reinterpreted). This table
    is the ONLY behavioral pregnancy state: when `is_active` is true the
    reproductive estimate endpoint returns SUPPRESSED.

    - Singleton per user (`user_id` PK); absence = never entered pregnancy
      mode. `is_active = FALSE` retains the row (history) with mode off;
      `DELETE` erases it (GDPR-style erasure).
    - `estimated_due_date` / `lmp_date` / `confirmation_date` are USER-LOCAL
      calendar DATEs (never shifted through UTC).
    - `dating_source` preserves provenance; `dating_note` is verbatim text
      (never parsed into medical facts).
    - Mode is entered/exited ONLY through the explicit pregnancy endpoints.
      Cycle logging, symptom logging, health-context selections, predictions,
      and estimates never flip it. No automatic activation from late periods,
      no automatic deactivation when EDD passes or a period is logged.
    """

    __tablename__ = "pregnancy_contexts"
    __table_args__ = (
        CheckConstraint(
            "dating_source IS NULL OR dating_source IN "
            "('lmp', 'ultrasound', 'clinician', 'unknown')",
            name="ck_pregnancy_dating_source",
        ),
        # EDD requires a known dating source; 'unknown'/NULL source implies
        # unavailable EDD (explicit unknown state, never invented).
        CheckConstraint(
            "(estimated_due_date IS NULL) OR "
            "(dating_source IN ('lmp', 'ultrasound', 'clinician'))",
            name="ck_pregnancy_edd_requires_known_source",
        ),
        # lmp_date is provenance for LMP-based dating only.
        CheckConstraint(
            "(lmp_date IS NULL) OR (dating_source = 'lmp')",
            name="ck_pregnancy_lmp_only_for_lmp_source",
        ),
        # Static chronological orderings (no 280-day formula enforced here:
        # the server stores EDDs verbatim and never auto-computes them).
        CheckConstraint(
            "(lmp_date IS NULL OR estimated_due_date IS NULL "
            "OR lmp_date <= estimated_due_date)",
            name="ck_pregnancy_lmp_before_edd",
        ),
        CheckConstraint(
            "(confirmation_date IS NULL OR estimated_due_date IS NULL "
            "OR confirmation_date <= estimated_due_date)",
            name="ck_pregnancy_confirmation_before_edd",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("profiles.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    dating_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    estimated_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    lmp_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    confirmation_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    dating_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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

    user: Mapped["Profile"] = relationship("Profile", back_populates="pregnancy_context")
