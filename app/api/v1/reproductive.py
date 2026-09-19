import uuid
from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.fertility_observation import FertilityObservation
from app.models.pregnancy_context import PregnancyContext
from app.schemas.fertility import (
    FertilityEstimateResponse,
    FertilityObservationCreate,
    FertilityObservationResponse,
    FertilityObservationUpdate,
    ObservationTypeEnum,
)
from app.schemas.pregnancy import (
    PREGNANCY_SAFETY_NOTE,
    PregnancyPatch,
    PregnancyPut,
    PregnancyResponse,
)
from app.schemas.reproductive_aging import (
    AGING_PROVENANCE_USER_DECLARED,
    AGING_SAFETY_NOTE,
    AgingContextPut,
    AgingContextResponse,
)
from app.services.reproductive_aging import apply_aging_put, get_aging_row
from app.services.fertility_estimator import get_fertility_estimate
from app.services.pregnancy import (
    PregnancyConflictError,
    PregnancyValidationError,
    apply_pregnancy_patch,
    apply_pregnancy_put,
    delete_pregnancy_row,
    get_pregnancy_row,
)
from app.services.pregnancy_dating import (
    compute_gestational_age_total_days,
    dating_confidence_for,
    edd_label_for,
    split_weeks_days,
)
from app.services.profile import get_or_create_profile
from app.services.timezone import user_today, user_today_for

router = APIRouter(prefix="/reproductive", tags=["Reproductive"])

UNPROCESSABLE = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

REPRODUCTIVE_SAFETY_NOTE = (
    "Fertility data only. Observations record what was measured; estimates are "
    "educational and are never contraception, never a diagnosis, and never a "
    "guarantee of fertility or infertility."
)

PREGNANCY_ENDPOINT_NOTE = (
    "Explicit user-controlled pregnancy mode. Activating or updating pregnancy "
    "mode never deletes historical periods, cycles, observations, logs, or "
    "symptoms; it is a context change only. " + PREGNANCY_SAFETY_NOTE
)

AGING_ENDPOINT_NOTE = (
    "Explicit user-controlled reproductive-aging context. Recording, changing, "
    "or clearing this context never deletes historical periods, cycles, "
    "observations, logs, symptoms, or pregnancy state; it is a context change "
    "only. " + AGING_SAFETY_NOTE
)


def _aging_to_response(
    row,
    *,
    user_id: uuid.UUID,
) -> AgingContextResponse:
    """Build the user-context representation from the stored singleton.

    Stored notes are returned verbatim. Provenance is a fixed
    user-declared label (the row can only ever reflect explicit user input).
    Absence (or NULL notes) yields has_context False — never an inferred
    state and never a diagnosis. No cycle, fertility, pregnancy, or
    prediction data is read or modified here.
    """
    notes = row.notes if row else None
    return AgingContextResponse(
        user_id=user_id,
        has_context=bool(notes is not None),
        notes=notes,
        provenance=AGING_PROVENANCE_USER_DECLARED,
        created_at=row.created_at if row else None,
        updated_at=row.updated_at if row else None,
    )


def _pregnancy_to_response(
    row: Optional[PregnancyContext],
    *,
    user_id: uuid.UUID,
    today: date,
    timezone_name: str,
) -> PregnancyResponse:
    """Build the derived dating representation from the stored basis.

    Stored values are returned verbatim (history is retained visibly when
    `is_active` is false). Derived fields come from the stored dating basis
    + the user's local as-of date. Absent dating yields an explicit
    unavailable state (nulls) — never an invented EDD and never an arbitrary
    fallback. Clients should present gestational age as current only when
    `is_active` is true.
    """
    source = row.dating_source if row else None
    edd = row.estimated_due_date if row else None
    lmp = row.lmp_date if row else None
    total_days = compute_gestational_age_total_days(
        estimated_due_date=edd,
        lmp_date=lmp,
        as_of=today,
    )
    weeks, days = split_weeks_days(total_days)
    return PregnancyResponse(
        user_id=user_id,
        is_active=bool(row is not None and row.is_active),
        dating_source=source,
        estimated_due_date=edd,
        lmp_date=lmp,
        confirmation_date=row.confirmation_date if row else None,
        dating_note=row.dating_note if row else None,
        edd_status="available" if edd is not None else "unavailable",
        edd_label=edd_label_for(source),
        dating_confidence=dating_confidence_for(source),
        gestational_age_total_days=total_days,
        gestational_age_weeks=weeks,
        gestational_age_days=days,
        days_until_due=(edd - today).days if edd is not None else None,
        as_of_date=today,
        timezone_name=timezone_name,
        created_at=row.created_at if row else None,
        updated_at=row.updated_at if row else None,
    )


def _to_response(row: FertilityObservation) -> FertilityObservationResponse:
    return FertilityObservationResponse.model_validate(row)


def _value_for_type(payload: FertilityObservationCreate) -> dict:
    kind = payload.observation_type
    if kind == ObservationTypeEnum.lh_test:
        return {
            "lh_result": payload.lh_result.value if payload.lh_result else None,
            "bbt_celsius": None,
            "mucus_category": None,
        }
    if kind == ObservationTypeEnum.bbt:
        return {
            "lh_result": None,
            "bbt_celsius": payload.bbt_celsius,
            "mucus_category": None,
        }
    return {
        "lh_result": None,
        "bbt_celsius": None,
        "mucus_category": payload.mucus_category.value if payload.mucus_category else None,
    }


@router.post(
    "/observations",
    response_model=FertilityObservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a fertility observation (upsert per day/type)",
    description="Stores one user-measured fact (LH/BBT/cervical mucus). "
    "Re-posting the same (date, type) overwrites deterministically (200) "
    "while first creation answers 201. " + REPRODUCTIVE_SAFETY_NOTE,
)
async def create_observation(
    payload: FertilityObservationCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await get_or_create_profile(db, current_user_id)
    today = user_today(profile.timezone)
    obs_date = payload.observation_date or today
    if obs_date > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="observation_date cannot be in the future",
        )

    values = _value_for_type(payload)
    stmt = select(FertilityObservation).where(
        FertilityObservation.user_id == current_user_id,
        FertilityObservation.observation_date == obs_date,
        FertilityObservation.observation_type == payload.observation_type.value,
    )
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()

    def _overwrite(target: FertilityObservation) -> JSONResponse:
        target.lh_result = values["lh_result"]
        target.bbt_celsius = values["bbt_celsius"]
        target.mucus_category = values["mucus_category"]
        target.source = payload.source.value
        target.note = payload.note
        return target

    if existing is not None:
        _overwrite(existing)
        await db.commit()
        await db.refresh(existing)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(_to_response(existing)),
        )

    row = FertilityObservation(
        user_id=current_user_id,
        observation_date=obs_date,
        observation_type=payload.observation_type.value,
        lh_result=values["lh_result"],
        bbt_celsius=values["bbt_celsius"],
        mucus_category=values["mucus_category"],
        source=payload.source.value,
        note=payload.note,
    )
    db.add(row)
    try:
        await db.commit()
        await db.refresh(row)
    except IntegrityError:
        # True race on the (user, date, type) key: converge last-writer-wins.
        await db.rollback()
        res = await db.execute(stmt)
        raced = res.scalar_one_or_none()
        if raced is None:
            raise
        _overwrite(raced)
        await db.commit()
        await db.refresh(raced)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=jsonable_encoder(_to_response(raced)),
        )
    return _to_response(row)


@router.get(
    "/observations",
    response_model=List[FertilityObservationResponse],
    summary="List own fertility observations in an optional date range",
    description="Returns the authenticated user's observations newest-first. " + REPRODUCTIVE_SAFETY_NOTE,
)
async def list_observations(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    observation_type: Optional[ObservationTypeEnum] = Query(default=None),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[FertilityObservation]:
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=UNPROCESSABLE,
            detail="start_date cannot be after end_date",
        )
    stmt = select(FertilityObservation).where(
        FertilityObservation.user_id == current_user_id
    )
    if start_date:
        stmt = stmt.where(FertilityObservation.observation_date >= start_date)
    if end_date:
        stmt = stmt.where(FertilityObservation.observation_date <= end_date)
    if observation_type:
        stmt = stmt.where(
            FertilityObservation.observation_type == observation_type.value
        )
    stmt = stmt.order_by(
        desc(FertilityObservation.observation_date),
        desc(FertilityObservation.id),
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.patch(
    "/observations/{observation_id}",
    response_model=FertilityObservationResponse,
    summary="Correct a fertility observation",
    description="Partial update. observation_type is immutable: value fields "
    "must match the row's own type. Explicitly passing null clears note. "
    + REPRODUCTIVE_SAFETY_NOTE,
)
async def update_observation(
    observation_id: int,
    payload: FertilityObservationUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FertilityObservation:
    stmt = select(FertilityObservation).where(
        FertilityObservation.id == observation_id,
        FertilityObservation.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fertility observation not found",
        )

    fields_set = payload.model_fields_set
    kind = row.observation_type
    for field_name, owner in (
        ("lh_result", "lh_test"),
        ("bbt_celsius", "bbt"),
        ("mucus_category", "cervical_mucus"),
    ):
        if field_name in fields_set and getattr(payload, field_name) is not None and kind != owner:
            raise HTTPException(
                status_code=UNPROCESSABLE,
                detail=f"{field_name} is only valid for {owner} observations",
            )

    if "observation_date" in fields_set and payload.observation_date is not None:
        today = await user_today_for(db, current_user_id)
        if payload.observation_date > today:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="observation_date cannot be in the future",
            )
        clash_stmt = select(FertilityObservation).where(
            FertilityObservation.user_id == current_user_id,
            FertilityObservation.observation_date == payload.observation_date,
            FertilityObservation.observation_type == row.observation_type,
            FertilityObservation.id != row.id,
        )
        clash = (await db.execute(clash_stmt)).scalar_one_or_none()
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An observation of this type already exists on that date.",
            )
        row.observation_date = payload.observation_date

    if "lh_result" in fields_set and kind == "lh_test":
        row.lh_result = payload.lh_result.value if payload.lh_result else None
    if "bbt_celsius" in fields_set and kind == "bbt":
        row.bbt_celsius = payload.bbt_celsius
    if "mucus_category" in fields_set and kind == "cervical_mucus":
        row.mucus_category = payload.mucus_category.value if payload.mucus_category else None
    if "source" in fields_set and payload.source is not None:
        row.source = payload.source.value
    if "note" in fields_set:
        row.note = payload.note

    await db.commit()
    await db.refresh(row)
    return row


@router.delete(
    "/observations/{observation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retract a fertility observation",
)
async def delete_observation(
    observation_id: int,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(FertilityObservation).where(
        FertilityObservation.id == observation_id,
        FertilityObservation.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fertility observation not found",
        )
    await db.delete(row)
    await db.commit()
    return None


@router.get(
    "/estimates",
    response_model=FertilityEstimateResponse,
    summary="Read the server-computed estimated fertility state",
    description="Computed on read from observed periods + observations, so every "
    "observed-data change is reflected immediately. Client read-only: there is "
    "no write path for estimates. INSUFFICIENT_DATA/LOW_CONFIDENCE answers "
    "carry null dates (never fabricated) with HTTP 200. " + REPRODUCTIVE_SAFETY_NOTE,
)
async def read_estimate(
    as_of: Optional[date] = Query(
        default=None,
        description="User-local as-of date to compute for; defaults to the user's local today. Must not be future.",
    ),
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        estimate = await get_fertility_estimate(db, current_user_id, as_of=as_of)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return estimate.to_response_dict()


# --- Explicit pregnancy mode (Phase 3) --------------------------------------
# Separate from the legacy health_contexts.pregnancy_context free selection,
# which is never read or written here and keeps zero behavioral effect.


async def _pregnancy_today_and_label(db: AsyncSession, user_id: uuid.UUID):
    # Read-only resolver for GET: never creates a profile as a side effect
    # (mirrors health-context GET defaults-when-unset). PUT/PATCH ensure the
    # profile via the service layer instead.
    from app.models.profile import Profile

    res = await db.execute(select(Profile.timezone).where(Profile.user_id == user_id))
    tz_name = res.scalar_one_or_none()
    today = user_today(tz_name)
    label = tz_name.strip() if tz_name and tz_name.strip() else "UTC (profile timezone unset)"
    return today, label


def _map_pregnancy_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PregnancyConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=str(exc),
    )


@router.get(
    "/pregnancy",
    response_model=PregnancyResponse,
    summary="Read the authenticated user's pregnancy mode and dating",
    description="Returns the explicit pregnancy-mode singleton, or an inactive "
    "unset default when never entered (mirrors health-context "
    "defaults-when-unset). Dating fields are stored verbatim; gestational age "
    "is derived read-only from the stored basis and the user's local date. "
    + PREGNANCY_ENDPOINT_NOTE,
)
async def read_pregnancy(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PregnancyResponse:
    today, label = await _pregnancy_today_and_label(db, current_user_id)
    row = await get_pregnancy_row(db, current_user_id)
    return _pregnancy_to_response(row, user_id=current_user_id, today=today, timezone_name=label)


@router.put(
    "/pregnancy",
    response_model=PregnancyResponse,
    summary="Activate or replace pregnancy mode (full sync upsert)",
    description="Full replacement for offline-first sync: every dating field is "
    "set from the payload and omitted fields clear to null; is_active "
    "defaults to true (activation intent). Creates the row on first sync. "
    "Explicit only: nothing else activates pregnancy mode. A "
    "lower-provenance due date cannot silently replace a stored "
    "higher-provenance due date (409). " + PREGNANCY_ENDPOINT_NOTE,
)
async def put_pregnancy(
    payload: PregnancyPut,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PregnancyResponse:
    today, label = await _pregnancy_today_and_label(db, current_user_id)
    try:
        row = await apply_pregnancy_put(
            db,
            current_user_id,
            is_active=payload.is_active,
            dating_source=payload.dating_source,
            estimated_due_date=payload.estimated_due_date,
            lmp_date=payload.lmp_date,
            confirmation_date=payload.confirmation_date,
            dating_note=payload.dating_note,
            today=today,
        )
    except (PregnancyValidationError, PregnancyConflictError) as exc:
        raise _map_pregnancy_error(exc)
    return _pregnancy_to_response(row, user_id=current_user_id, today=today, timezone_name=label)


@router.patch(
    "/pregnancy",
    response_model=PregnancyResponse,
    summary="Partially update pregnancy mode",
    description="Only fields explicitly included change; explicit null clears. "
    "Deactivation is explicit via {is_active:false} (history retained) — "
    "never automatic. Same 409 provenance protection as PUT. "
    + PREGNANCY_ENDPOINT_NOTE,
)
async def patch_pregnancy(
    payload: PregnancyPatch,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PregnancyResponse:
    today, label = await _pregnancy_today_and_label(db, current_user_id)
    try:
        row = await apply_pregnancy_patch(
            db,
            current_user_id,
            fields_set=payload.model_fields_set,
            is_active=payload.is_active,
            dating_source=payload.dating_source,
            estimated_due_date=payload.estimated_due_date,
            lmp_date=payload.lmp_date,
            confirmation_date=payload.confirmation_date,
            dating_note=payload.dating_note,
            today=today,
        )
    except (PregnancyValidationError, PregnancyConflictError) as exc:
        raise _map_pregnancy_error(exc)
    return _pregnancy_to_response(row, user_id=current_user_id, today=today, timezone_name=label)


@router.delete(
    "/pregnancy",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Erase pregnancy state (explicit exit with erasure)",
    description="Hard-deletes the singleton row. Distinct from PATCH "
    "{is_active:false}, which pauses mode and retains history. "
    + PREGNANCY_ENDPOINT_NOTE,
)
async def delete_pregnancy(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_pregnancy_row(db, current_user_id)
    return None


# --- Explicit reproductive-aging context (Phase 4) ---------------------------
# User-owned free-text singleton only (Phase 1 contract §4.3/§5.8/§11).
# No staging enum, no diagnosis, no dates, no detection: the contract defines
# no state vocabulary, so none is invented. Independent of pregnancy mode
# (both singletons may coexist; neither flips the other) and with zero
# effect on period predictions and fertility estimates.


@router.get(
    "/aging-context",
    response_model=AgingContextResponse,
    summary="Read the authenticated user's reproductive-aging context",
    description="Returns the explicit user-recorded context, or an unset "
    "default (has_context False) when never recorded or cleared — mirrors "
    "health-context defaults-when-unset. Notes are verbatim user input, "
    "labeled with user-declared provenance. Never a diagnosis. "
    + AGING_ENDPOINT_NOTE,
)
async def read_aging_context(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgingContextResponse:
    # Read-only: never creates a profile or a row as a side effect (mirrors
    # the pregnancy GET resolver pattern).
    row = await get_aging_row(db, current_user_id)
    return _aging_to_response(row, user_id=current_user_id)


@router.put(
    "/aging-context",
    response_model=AgingContextResponse,
    summary="Record or replace reproductive-aging context (full sync upsert)",
    description="Full replacement for offline-first sync: notes is set from "
    "the payload and an omitted/null value clears the recorded context. "
    "Creates the row on first sync. Explicit only: cycle logging, symptom "
    "logging, health-context selections, predictions, estimates, and "
    "pregnancy mode never change this context. " + AGING_ENDPOINT_NOTE,
)
async def put_aging_context(
    payload: AgingContextPut,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgingContextResponse:
    row = await apply_aging_put(db, current_user_id, notes=payload.notes)
    return _aging_to_response(row, user_id=current_user_id)
