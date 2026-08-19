from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.core.idempotency import require_idempotency_key
from app.db.supabase_client import get_supabase
from app.modules.payments import service
from app.modules.payments.schemas import PaymentCreate, PaymentRead
from app.modules.users.schemas import UserRead

router = APIRouter()


@router.post("", response_model=PaymentRead, status_code=201)
async def create_payment(
    payload: PaymentCreate,
    idempotency_key: str = Depends(require_idempotency_key),
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> dict:
    return await service.create_payment(supabase, user, payload, idempotency_key)


@router.get("", response_model=list[PaymentRead])
async def list_payments(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[dict]:
    return await service.list_payments(supabase, user)
