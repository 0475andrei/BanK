from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.modules.card_orders import service
from app.modules.card_orders.models import CardOrder
from app.modules.card_orders.schemas import CardOrderCreate, CardOrderRead
from app.modules.users.models import User

router = APIRouter()


@router.post("", response_model=CardOrderRead, status_code=201)
async def create_order(
    payload: CardOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CardOrder:
    return await service.create_order(db, user, payload)


@router.get("", response_model=list[CardOrderRead])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CardOrder]:
    return await service.list_orders(db, user)
