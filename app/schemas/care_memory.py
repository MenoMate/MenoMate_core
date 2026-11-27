from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field


class CareMemoryCategory(str, Enum):
    communication_preference = "communication_preference"
    care_preference = "care_preference"
    device_preference = "device_preference"
    context_note = "context_note"


class CareMemorySource(str, Enum):
    user_explicit = "user_explicit"
    history_supported = "history_supported"


class CareMemoryUpsert(BaseModel):
    category: CareMemoryCategory
    key: str = Field(..., min_length=1, max_length=64)
    value: str = Field(..., min_length=1, max_length=256)
    source: CareMemorySource = CareMemorySource.user_explicit


class CareMemoryUpdate(BaseModel):
    value: Optional[str] = Field(default=None, min_length=1, max_length=256)
    is_active: Optional[bool] = None


class CareMemoryResponse(BaseModel):
    id: int
    category: str
    key: str
    value: str
    source: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
