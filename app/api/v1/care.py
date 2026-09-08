import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.schemas.care import CareInteractionRequest, CareInteractionResponse
from app.services.care import handle_care_interaction

router = APIRouter(prefix="/care", tags=["MenoMate Care Guided Assistance"])


@router.post(
    "/interactions",
    response_model=CareInteractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Guided Care interaction endpoint (deterministic or compact AI response)",
)
@router.post(
    "/interact",
    response_model=CareInteractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Guided Care interaction endpoint alias",
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
    )
    return CareInteractionResponse(**interaction_data)
