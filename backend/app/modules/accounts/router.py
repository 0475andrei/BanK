import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.modules.accounts import service
from app.modules.accounts.models import Account
from app.modules.accounts.schemas import AccountCreate, AccountRead
from app.modules.ledger import service as ledger_service
from app.modules.users.models import User

router = APIRouter()


async def _to_read_model(db: AsyncSession, account: Account) -> AccountRead:
    balance_minor = await ledger_service.get_balance(db, account.id)
    return AccountRead(
        id=account.id,
        name=account.name,
        currency=account.currency,
        status=account.status,
        balance_minor=balance_minor,
        created_at=account.created_at,
    )


@router.post("", response_model=AccountRead, status_code=201)
async def open_account(
    payload: AccountCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AccountRead:
    account = await service.open_account(db, user, payload.name, payload.currency)
    return await _to_read_model(db, account)


@router.get("", response_model=list[AccountRead])
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[AccountRead]:
    accounts = await service.list_accounts(db, user)
    return [await _to_read_model(db, account) for account in accounts]


@router.get("/{account_id}", response_model=AccountRead)
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AccountRead:
    account = await service.get_account(db, user, account_id)
    return await _to_read_model(db, account)


@router.post("/{account_id}/close", response_model=AccountRead)
async def close_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AccountRead:
    account = await service.close_account(db, user, account_id)
    return await _to_read_model(db, account)
