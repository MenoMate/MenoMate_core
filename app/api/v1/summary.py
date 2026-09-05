import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.schemas.summary import CurrentSummaryResponse, HistorySummaryResponse
from app.services.summary import get_current_cycle_summary, get_history_summary

router = APIRouter(prefix="/summary", tags=["Summary & Analytics"])


@router.get(
    "/current",
    response_model=CurrentSummaryResponse,
    summary="Get home screen summary (current cycle day, phase, next period, today's log)",
)
async def get_current_summary(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CurrentSummaryResponse:
    summary_data = await get_current_cycle_summary(db, current_user_id)
    return CurrentSummaryResponse(**summary_data)


@router.get(
    "/history",
    response_model=HistorySummaryResponse,
    summary="Get historical cycle list, average lengths, variability, and symptom distribution",
)
async def get_cycle_history(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> HistorySummaryResponse:
    history_data = await get_history_summary(db, current_user_id)
    return HistorySummaryResponse(**history_data)
