import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class DeviceCreate(BaseModel):
    device_identifier: str = Field(..., max_length=128, description="Unique hardware identifier (MAC or BLE UUID)")
    name: Optional[str] = Field(default=None, max_length=128)
    firmware_version: Optional[str] = Field(default=None, max_length=64)


class DeviceResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    device_identifier: str
    name: Optional[str] = None
    firmware_version: Optional[str] = None
    last_connected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
