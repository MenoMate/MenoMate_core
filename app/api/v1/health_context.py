import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.health_context import HealthCondition, HealthContext, Medication
from app.schemas.health_context import (
    HealthConditionCreate,
    HealthConditionResponse,
    HealthConditionUpdate,
    HealthContextResponse,
    HealthContextUpdate,
    HealthContextUpsert,
    MedicationCreate,
    MedicationResponse,
    MedicationUpdate,
    validate_condition_label,
)
from app.services.profile import get_or_create_profile

router = APIRouter(prefix="/health-context", tags=["Health Context"])

HEALTH_SAFETY_NOTE = (
    "User-provided health context only. MenoMate does not diagnose, does not "
    "infer conditions, and does not let this data alter predictions."
)


async def _find_duplicate_condition(
    db: AsyncSession,
    user_id: uuid.UUID,
    condition_code: str,
    custom_label: Optional[str],
    exclude_id: Optional[int] = None,
) -> Optional[HealthCondition]:
    stmt = select(HealthCondition).where(
        HealthCondition.user_id == user_id,
        HealthCondition.condition_code == condition_code,
    )
    if custom_label is None:
        stmt = stmt.where(HealthCondition.custom_label.is_(None))
    else:
        stmt = stmt.where(HealthCondition.custom_label == custom_label)
    if exclude_id is not None:
        stmt = stmt.where(HealthCondition.id != exclude_id)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


def _apply_label_contract(condition_code: str, custom_label: Optional[str]) -> Optional[str]:
    try:
        return validate_condition_label(condition_code, custom_label)
    except ValueError as exc:
        raise HTTPException(
            status_code=getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422),
            detail=str(exc),
        )


@router.get(
    "",
    response_model=HealthContextResponse,
    summary="Get the authenticated user's health context",
    description="Returns contraception, pregnancy/fertility selections, and free-text context. "
    "Unset fields are null. " + HEALTH_SAFETY_NOTE,
)
async def get_health_context(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthContextResponse:
    stmt = select(HealthContext).where(HealthContext.user_id == current_user_id)
    res = await db.execute(stmt)
    context = res.scalar_one_or_none()
    if context is None:
        return HealthContextResponse(user_id=current_user_id)
    return HealthContextResponse.model_validate(context)


@router.put(
    "",
    response_model=HealthContextResponse,
    summary="Replace the authenticated user's health context (full sync upsert)",
    description=(
        "Full replacement for offline-first sync: every field is set from the payload, "
        "and omitted fields are cleared to null. Creates the record on first sync. "
        + HEALTH_SAFETY_NOTE
    ),
)
async def put_health_context(
    payload: HealthContextUpsert,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthContext:
    await get_or_create_profile(db, current_user_id)
    stmt = select(HealthContext).where(HealthContext.user_id == current_user_id)
    res = await db.execute(stmt)
    context = res.scalar_one_or_none()
    if context is None:
        context = HealthContext(user_id=current_user_id)
        db.add(context)

    context.contraception_method = payload.contraception_method.value if payload.contraception_method else None
    context.contraception_note = payload.contraception_note
    context.pregnancy_context = payload.pregnancy_context.value if payload.pregnancy_context else None
    context.health_notes = payload.health_notes

    await db.commit()
    await db.refresh(context)
    return context


@router.patch(
    "",
    response_model=HealthContextResponse,
    summary="Partially update the authenticated user's health context",
    description=(
        "Only fields explicitly included in the request payload are modified. "
        "Explicitly passing null clears the corresponding optional field. "
        + HEALTH_SAFETY_NOTE
    ),
)
async def patch_health_context(
    payload: HealthContextUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthContext:
    await get_or_create_profile(db, current_user_id)
    stmt = select(HealthContext).where(HealthContext.user_id == current_user_id)
    res = await db.execute(stmt)
    context = res.scalar_one_or_none()
    if context is None:
        context = HealthContext(user_id=current_user_id)
        db.add(context)

    fields_set = payload.model_fields_set
    if "contraception_method" in fields_set:
        context.contraception_method = payload.contraception_method.value if payload.contraception_method else None
    if "contraception_note" in fields_set:
        context.contraception_note = payload.contraception_note
    if "pregnancy_context" in fields_set:
        context.pregnancy_context = payload.pregnancy_context.value if payload.pregnancy_context else None
    if "health_notes" in fields_set:
        context.health_notes = payload.health_notes

    await db.commit()
    await db.refresh(context)
    return context


@router.get(
    "/conditions",
    response_model=List[HealthConditionResponse],
    summary="List the authenticated user's reported health conditions",
    description="User-reported context, not MenoMate diagnoses. " + HEALTH_SAFETY_NOTE,
)
async def list_health_conditions(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[HealthCondition]:
    stmt = (
        select(HealthCondition)
        .where(HealthCondition.user_id == current_user_id)
        .order_by(HealthCondition.id.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post(
    "/conditions",
    response_model=HealthConditionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a user-reported health condition",
    description="Stores user-reported context, not a diagnosis. " + HEALTH_SAFETY_NOTE,
)
async def create_health_condition(
    payload: HealthConditionCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthCondition:
    await get_or_create_profile(db, current_user_id)
    custom_label = _apply_label_contract(payload.condition_code, payload.custom_label)

    if await _find_duplicate_condition(db, current_user_id, payload.condition_code, custom_label):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This condition is already recorded for this user.",
        )

    condition = HealthCondition(
        user_id=current_user_id,
        condition_code=payload.condition_code,
        custom_label=custom_label,
        note=payload.note,
        is_active=payload.is_active,
    )
    db.add(condition)
    try:
        await db.commit()
        await db.refresh(condition)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This condition is already recorded for this user.",
        )
    return condition


@router.patch(
    "/conditions/{condition_id}",
    response_model=HealthConditionResponse,
    summary="Update a user-reported health condition",
    description=(
        "Only fields explicitly included in the request payload are modified. "
        "Explicitly passing null clears the corresponding optional field. "
        + HEALTH_SAFETY_NOTE
    ),
)
async def update_health_condition(
    condition_id: int,
    payload: HealthConditionUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HealthCondition:
    stmt = select(HealthCondition).where(
        HealthCondition.id == condition_id,
        HealthCondition.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    condition = res.scalar_one_or_none()
    if not condition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Health condition not found")

    fields_set = payload.model_fields_set
    new_code = payload.condition_code if "condition_code" in fields_set else condition.condition_code
    new_label_raw = payload.custom_label if "custom_label" in fields_set else condition.custom_label
    new_label = _apply_label_contract(new_code, new_label_raw)

    if await _find_duplicate_condition(db, current_user_id, new_code, new_label, exclude_id=condition_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This condition is already recorded for this user.",
        )

    condition.condition_code = new_code
    condition.custom_label = new_label
    if "note" in fields_set:
        condition.note = payload.note
    if payload.is_active is not None:
        condition.is_active = payload.is_active

    try:
        await db.commit()
        await db.refresh(condition)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This condition is already recorded for this user.",
        )
    return condition


@router.delete(
    "/conditions/{condition_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a user-reported health condition",
)
async def delete_health_condition(
    condition_id: int,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(HealthCondition).where(
        HealthCondition.id == condition_id,
        HealthCondition.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    condition = res.scalar_one_or_none()
    if not condition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Health condition not found")

    await db.delete(condition)
    await db.commit()
    return None


@router.get(
    "/medications",
    response_model=List[MedicationResponse],
    summary="List the authenticated user's medications/treatments",
    description="User-provided context only; no medication advice is given. " + HEALTH_SAFETY_NOTE,
)
async def list_medications(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Medication]:
    stmt = (
        select(Medication)
        .where(Medication.user_id == current_user_id)
        .order_by(Medication.id.asc())
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post(
    "/medications",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a user-provided medication or treatment",
    description="Stores user-provided context only. " + HEALTH_SAFETY_NOTE,
)
async def create_medication(
    payload: MedicationCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Medication:
    await get_or_create_profile(db, current_user_id)
    medication = Medication(
        user_id=current_user_id,
        name=payload.name,
        note=payload.note,
        is_active=payload.is_active,
    )
    db.add(medication)
    await db.commit()
    await db.refresh(medication)
    return medication


@router.patch(
    "/medications/{medication_id}",
    response_model=MedicationResponse,
    summary="Update a user-provided medication or treatment",
    description=(
        "Only fields explicitly included in the request payload are modified. "
        "Explicitly passing null clears the corresponding optional field. "
        + HEALTH_SAFETY_NOTE
    ),
)
async def update_medication(
    medication_id: int,
    payload: MedicationUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Medication:
    stmt = select(Medication).where(
        Medication.id == medication_id,
        Medication.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    medication = res.scalar_one_or_none()
    if not medication:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found")

    fields_set = payload.model_fields_set
    if "name" in fields_set and payload.name is not None:
        medication.name = payload.name
    if "note" in fields_set:
        medication.note = payload.note
    if payload.is_active is not None:
        medication.is_active = payload.is_active

    await db.commit()
    await db.refresh(medication)
    return medication


@router.delete(
    "/medications/{medication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a user-provided medication or treatment",
)
async def delete_medication(
    medication_id: int,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Medication).where(
        Medication.id == medication_id,
        Medication.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    medication = res.scalar_one_or_none()
    if not medication:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Medication not found")

    await db.delete(medication)
    await db.commit()
    return None
