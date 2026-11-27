import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.care_memory import CareMemory
from app.schemas.care import CareInteractionRequest, CareInteractionResponse
from app.schemas.care_memory import (
    CareMemoryResponse,
    CareMemoryUpdate,
    CareMemoryUpsert,
)
from app.schemas.insights import PatternAnalysisResult
from app.services.care import handle_care_interaction
from app.services.personal_context import build_personal_care_context
from app.services.profile import get_or_create_profile

router = APIRouter(prefix="/care", tags=["MenoMate Care Guided Assistance"])


@router.post(
    "/interactions",
    response_model=CareInteractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Guided Care interaction endpoint (deterministic or compact AI response)",
)
async def care_interaction(
    payload: CareInteractionRequest,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CareInteractionResponse:
    interaction_data = await handle_care_interaction(
        db=db,
        user_id=current_user_id,
        intent=payload.intent,
        user_message=payload.user_message,
        recent_turns=[t.model_dump() for t in payload.recent_turns],
    )
    return CareInteractionResponse(**interaction_data)


@router.get(
    "/insights",
    response_model=PatternAnalysisResult,
    summary="Retrieve evidence-backed personal patterns and insights",
)
async def get_personal_insights(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PatternAnalysisResult:
    ctx = await build_personal_care_context(
        db, current_user_id, intent="pattern_summary"
    )
    return PatternAnalysisResult(
        insights=ctx.insights,
        pain_trend=ctx.pain_trend,
        device_preference_summary=ctx.device_preference_summary,
        tracking_completeness=ctx.tracking_completeness,
    )


@router.get(
    "/memories",
    response_model=List[CareMemoryResponse],
    summary="List saved Care preferences and structured memories",
)
async def list_care_memories(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[CareMemory]:
    stmt = (
        select(CareMemory)
        .where(CareMemory.user_id == current_user_id, CareMemory.is_active.is_(True))
        .order_by(desc(CareMemory.updated_at))
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post(
    "/memories",
    response_model=CareMemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save or update a structured Care preference or memory",
)
async def upsert_care_memory(
    payload: CareMemoryUpsert,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CareMemory:
    await get_or_create_profile(db, current_user_id)
    stmt = select(CareMemory).where(
        CareMemory.user_id == current_user_id,
        CareMemory.category == payload.category.value,
        CareMemory.key == payload.key,
    )
    res = await db.execute(stmt)
    existing = res.scalar_one_or_none()
    if existing is not None:
        existing.value = payload.value
        existing.source = payload.source.value
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return existing

    mem = CareMemory(
        user_id=current_user_id,
        category=payload.category.value,
        key=payload.key,
        value=payload.value,
        source=payload.source.value,
        is_active=True,
    )
    db.add(mem)
    await db.commit()
    await db.refresh(mem)
    return mem


@router.patch(
    "/memories/{memory_id}",
    response_model=CareMemoryResponse,
    summary="Update an existing Care memory",
)
async def update_care_memory(
    memory_id: int,
    payload: CareMemoryUpdate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CareMemory:
    stmt = select(CareMemory).where(
        CareMemory.id == memory_id,
        CareMemory.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    mem = res.scalar_one_or_none()
    if mem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Care memory not found"
        )
    if payload.value is not None:
        mem.value = payload.value
    if payload.is_active is not None:
        mem.is_active = payload.is_active
    await db.commit()
    await db.refresh(mem)
    return mem


@router.delete(
    "/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved Care memory",
)
async def delete_care_memory(
    memory_id: int,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(CareMemory).where(
        CareMemory.id == memory_id,
        CareMemory.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    mem = res.scalar_one_or_none()
    if mem is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Care memory not found"
        )
    await db.delete(mem)
    await db.commit()
