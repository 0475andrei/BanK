import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.accounts.models import AccountStatus


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    currency: str = Field(min_length=3, max_length=3)


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    currency: str
    status: AccountStatus
    balance_minor: int
    created_at: datetime
