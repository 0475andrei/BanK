import uuid

from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.db.supabase_client import get_supabase
from app.modules.accounts import service
from app.modules.accounts.schemas import AccountCreate, AccountRead
from app.modules.ledger import service as ledger_service
from app.modules.users.schemas import UserRead

router = APIRouter()


async def _to_read_model(supabase: AsyncClient, account: dict) -> AccountRead:
    balance_minor = await ledger_service.get_balance(supabase, uuid.UUID(account["id"]))
    return AccountRead(
        id=account["id"],
        name=account["name"],
        currency=account["currency"],
        status=account["status"],
        balance_minor=balance_minor,
        created_at=account["created_at"],
    )


@router.post("", response_model=AccountRead, status_code=201)
async def open_account(
    payload: AccountCreate,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> AccountRead:
    account = await service.open_account(supabase, user, payload.name, payload.currency)
    return await _to_read_model(supabase, account)


@router.get("", response_model=list[AccountRead])
async def list_accounts(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[AccountRead]:
    accounts = await service.list_accounts(supabase, user)
    return [await _to_read_model(supabase, account) for account in accounts]


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: uuid.UUID,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> AccountRead:
    account = await service.get_account(supabase, user, account_id)
    return await _to_read_model(supabase, account)


@router.post("/{account_id}/close", response_model=AccountRead)
async def close_account(
    account_id: uuid.UUID,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> AccountRead:
    account = await service.close_account(supabase, user, account_id)
    return await _to_read_model(supabase, account)
