import uuid

from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.db.supabase_client import get_supabase
from app.modules.cards import service
from app.modules.cards.schemas import CardCreate, CardRead
from app.modules.users.schemas import UserRead

router = APIRouter()


@router.post("", response_model=CardRead, status_code=201)
async def issue_card(
    payload: CardCreate,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> dict:
    return await service.issue_card(supabase, user, payload)


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
