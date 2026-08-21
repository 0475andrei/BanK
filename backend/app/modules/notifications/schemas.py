import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime


class UnreadCountRead(BaseModel):
    count: int
