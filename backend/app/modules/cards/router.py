import uuid

from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.db.supabase_client import get_supabase
from app.modules.cards import service
from app.modules.cards.schemas import CardCreate, CardIssued, CardRead
from app.modules.users.schemas import UserRead

router = APIRouter()


@router.post("", response_model=CardIssued, status_code=201)
async def issue_card(
    payload: CardCreate,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> CardIssued:
    card, card_number = await service.issue_card(supabase, user, payload)
    return CardIssued(
        id=card["id"],
        account_id=card["account_id"],
        last4=card["last4"],
        status=card["status"],
        spending_limit_minor=card["spending_limit_minor"],
        created_at=card["created_at"],
        card_number=card_number,
    )


@router.get("", response_model=list[CardRead])
async def list_cards(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[dict]:
    return await service.list_cards(supabase, user)


@router.delete("/{card_id}", response_model=CardRead)
async def cancel_card(
    card_id: uuid.UUID,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> dict:
    return await service.cancel_card(supabase, user, card_id)
