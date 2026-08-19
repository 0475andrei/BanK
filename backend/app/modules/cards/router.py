import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.modules.cards import service
from app.modules.cards.models import Card
from app.modules.cards.schemas import CardCreate, CardRead
from app.modules.users.models import User

router = APIRouter()


@router.post("", response_model=CardRead, status_code=201)
async def issue_card(
    payload: CardCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Card:
    return await service.issue_card(db, user, payload)


@router.get("", response_model=list[CardRead])
async def list_cards(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Card]:
    return await service.list_cards(db, user)


@router.delete("/{card_id}", response_model=CardRead)
async def cancel_card(
    card_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Card:
    return await service.cancel_card(db, user, card_id)
