"""Phase 3 pregnancy-mode persistence (explicit user control only).

All writes are explicit authenticated user actions. Nothing here infers
pregnancy from late periods, predictions, or observations, and nothing here
touches the frozen period predictor, the prediction ledger, the backtest
harness, the timezone implementation, or Health Context semantics.
"""

import uuid
from datetime import date
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pregnancy_context import PregnancyContext
from app.services.profile import get_or_create_profile
from app.services.timezone import user_today


class PregnancyConflictError(Exception):
    """Lower-provenance EDD attempting to replace a higher-provenance EDD."""


class PregnancyValidationError(Exception):
    """Domain-rule violation (date ordering / joint-null rules)."""


def _source_str(value) -> Optional[str]:
    if value is None:
        return None
    return value.value if hasattr(value, "value") else str(value)


def validate_dating_fields(
    *,
    dating_source: Optional[str],
    estimated_due_date: Optional[date],
    lmp_date: Optional[date],
    confirmation_date: Optional[date],
    today: date,
) -> None:
    """Server-enforced joint/ordering rules. Raises PregnancyValidationError.

    - EDD requires a known source (lmp/ultrasound/clinician); 'unknown'/NULL
      source implies unavailable EDD (never invented).
    - lmp_date is provenance for lmp dating only.
    - lmp_date / confirmation_date must not be future vs the user's local today
      (routes resolve `today`; the schema holds only a coarse guard).
    - Static chronology: lmp <= EDD and confirmation <= EDD when both set.
    """
    if estimated_due_date is not None and dating_source not in ("lmp", "ultrasound", "clinician"):
        raise PregnancyValidationError(
            "estimated_due_date requires dating_source lmp, ultrasound, or clinician "
            "(unknown/unset means the due date is unavailable, not estimated)"
        )
    if lmp_date is not None and dating_source != "lmp":
        raise PregnancyValidationError("lmp_date is only valid with dating_source 'lmp'")
    if lmp_date is not None and lmp_date > today:
        raise PregnancyValidationError("lmp_date cannot be in the future")
    if confirmation_date is not None and confirmation_date > today:
        raise PregnancyValidationError("confirmation_date cannot be in the future")
    if lmp_date is not None and estimated_due_date is not None and lmp_date > estimated_due_date:
        raise PregnancyValidationError("lmp_date cannot be after estimated_due_date")
    if (
        confirmation_date is not None
        and estimated_due_date is not None
        and confirmation_date > estimated_due_date
    ):
        raise PregnancyValidationError("confirmation_date cannot be after estimated_due_date")


def check_downgrade_conflict(
    existing: Optional[PregnancyContext],
    *,
    incoming_source: Optional[str],
    incoming_edd: Optional[date],
) -> None:
    """Enforce dating hierarchy: raise PregnancyConflictError on a silent
    lower-over-higher EDD replacement with a differing date."""
    from app.services.pregnancy_dating import is_downgrade_conflict

    if existing is None or existing.estimated_due_date is None:
        return
    if is_downgrade_conflict(
        existing_source=existing.dating_source,
        existing_edd=existing.estimated_due_date,
        incoming_source=incoming_source,
        incoming_edd=incoming_edd,
    ):
        raise PregnancyConflictError(
            f"Stored {existing.dating_source}-based due date {existing.estimated_due_date} "
            f"has higher provenance than incoming {incoming_source}-based date {incoming_edd}; "
            "a lower-provenance source cannot silently replace it. Re-submit with the "
            "higher-provenance source, the same due date, or clear the stored dating first."
        )


async def get_pregnancy_row(db: AsyncSession, user_id: uuid.UUID) -> Optional[PregnancyContext]:
    res = await db.execute(select(PregnancyContext).where(PregnancyContext.user_id == user_id))
    return res.scalar_one_or_none()


async def is_pregnancy_mode_active(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Contextual flag for the estimate layer. Absence or is_active=False
    means inactive; never inferred from any other signal."""
    row = await get_pregnancy_row(db, user_id)
    return bool(row is not None and row.is_active)


async def apply_pregnancy_put(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    is_active: bool,
    dating_source,
    estimated_due_date,
    lmp_date,
    confirmation_date,
    dating_note: Optional[str],
    today: Optional[date] = None,
) -> PregnancyContext:
    """Full-replacement upsert: every dating field is set from the payload
    (omitted -> null). Creates the singleton row on first activation."""
    await get_or_create_profile(db, user_id)
    if today is None:
        today = await _resolve_today(db, user_id)
    source = _source_str(dating_source)
    validate_dating_fields(
        dating_source=source,
        estimated_due_date=estimated_due_date,
        lmp_date=lmp_date,
        confirmation_date=confirmation_date,
        today=today,
    )
    row = await get_pregnancy_row(db, user_id)
    if row is None:
        row = PregnancyContext(user_id=user_id)
        db.add(row)
    else:
        check_downgrade_conflict(row, incoming_source=source, incoming_edd=estimated_due_date)
    row.is_active = is_active
    row.dating_source = source
    row.estimated_due_date = estimated_due_date
    row.lmp_date = lmp_date
    row.confirmation_date = confirmation_date
    row.dating_note = dating_note
    await db.commit()
    await db.refresh(row)
    return row


async def apply_pregnancy_patch(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    fields_set: set,
    is_active=None,
    dating_source=None,
    estimated_due_date=None,
    lmp_date=None,
    confirmation_date=None,
    dating_note=None,
    today: Optional[date] = None,
) -> PregnancyContext:
    """Partial update: only explicitly included fields change; explicit null
    clears. Creates the row when absent (offline-restore friendly)."""
    await get_or_create_profile(db, user_id)
    if today is None:
        today = await _resolve_today(db, user_id)
    row = await get_pregnancy_row(db, user_id)
    if row is None:
        row = PregnancyContext(user_id=user_id)
        db.add(row)

    # Resolve the post-patch candidate for joint validation + conflict check.
    if "dating_source" in fields_set:
        candidate_source = _source_str(dating_source)
    else:
        candidate_source = row.dating_source
    candidate_edd = estimated_due_date if "estimated_due_date" in fields_set else row.estimated_due_date
    candidate_lmp = lmp_date if "lmp_date" in fields_set else row.lmp_date
    candidate_conf = (
        confirmation_date if "confirmation_date" in fields_set else row.confirmation_date
    )
    validate_dating_fields(
        dating_source=candidate_source,
        estimated_due_date=candidate_edd,
        lmp_date=candidate_lmp,
        confirmation_date=candidate_conf,
        today=today,
    )
    if "dating_source" in fields_set or "estimated_due_date" in fields_set:
        check_downgrade_conflict(
            row, incoming_source=candidate_source, incoming_edd=candidate_edd
        )

    if "is_active" in fields_set and is_active is not None:
        row.is_active = is_active
    if "dating_source" in fields_set:
        row.dating_source = candidate_source
    if "estimated_due_date" in fields_set:
        row.estimated_due_date = estimated_due_date
    if "lmp_date" in fields_set:
        row.lmp_date = lmp_date
    if "confirmation_date" in fields_set:
        row.confirmation_date = confirmation_date
    if "dating_note" in fields_set:
        row.dating_note = dating_note
    await db.commit()
    await db.refresh(row)
    return row


async def delete_pregnancy_row(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Hard-delete the singleton (GDPR-style erasure path). Returns True when
    a row existed; False (still 204) when there was nothing to erase."""
    row = await get_pregnancy_row(db, user_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def _resolve_today(db: AsyncSession, user_id: uuid.UUID) -> date:
    from sqlalchemy import select as _select

    from app.models.profile import Profile

    res = await db.execute(_select(Profile.timezone).where(Profile.user_id == user_id))
    tz_name = res.scalar_one_or_none()
    return user_today(tz_name)
