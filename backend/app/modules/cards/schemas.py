import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.cards.models import CardStatus


class CardCreate(BaseModel):
    account_id: uuid.UUID
    spending_limit_minor: int | None = Field(default=None, gt=0)


class CardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    last4: str
    status: CardStatus
    spending_limit_minor: int | None
    created_at: datetime


class CardIssued(CardRead):
    """Returned only by POST /cards - the one moment the full card number
    is ever visible. Not persisted anywhere; the caller must save it now."""

    card_number: str
