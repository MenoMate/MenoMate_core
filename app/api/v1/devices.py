import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.device import Device
from app.models.profile import Profile
from app.schemas.device import DeviceCreate, DeviceResponse

from app.services.profile import get_or_create_profile

router = APIRouter(prefix="/devices", tags=["Devices"])


@router.get(
    "",
    response_model=List[DeviceResponse],
    summary="List paired wearable devices for user",
)
async def list_devices(
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Device]:
    stmt = select(Device).where(Device.user_id == current_user_id)
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.post(
    "",
    response_model=DeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register or update a paired wearable device",
)
async def register_device(
    payload: DeviceCreate,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Device:
    await get_or_create_profile(db, current_user_id)

    # Check globally unique device_identifier
    stmt = select(Device).where(Device.device_identifier == payload.device_identifier)
    res = await db.execute(stmt)
    existing_device = res.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if existing_device is not None:
        if existing_device.user_id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Device identifier is already registered to another user account.",
            )
        # Update existing paired device for current user
        if payload.name is not None:
            existing_device.name = payload.name
        if payload.firmware_version is not None:
            existing_device.firmware_version = payload.firmware_version
        existing_device.last_connected_at = now
        device = existing_device
    else:
        device = Device(
            user_id=current_user_id,
            device_identifier=payload.device_identifier,
            name=payload.name,
            firmware_version=payload.firmware_version,
            last_connected_at=now,
        )
        db.add(device)

    await db.commit()
    await db.refresh(device)
    return device


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unpair a wearable device",
)
async def unpair_device(
    device_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Device).where(
        Device.id == device_id,
        Device.user_id == current_user_id,
    )
    res = await db.execute(stmt)
    device = res.scalar_one_or_none()

    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")

    await db.delete(device)
    await db.commit()
    return None
