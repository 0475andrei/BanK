import uuid

from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.db.supabase_client import get_supabase
from app.modules.accounts import service
from app.modules.accounts.schemas import (
    AccountCreate,
    AccountProductsRead,
    AccountRead,
    TermDepositOption,
)
from app.modules.ledger import service as ledger_service
from app.modules.users.schemas import UserRead

router = APIRouter()


async def _to_read_model(supabase: AsyncClient, account: dict) -> AccountRead:
    # Lazy accrual: a savings/term-deposit account's balance always
    # reflects interest earned so far, computed on every read rather than
    # on a schedule - see accounts/service.py::accrue_interest_if_due.
    await service.accrue_interest_if_due(supabase, account)
    balance_minor = await ledger_service.get_balance(supabase, uuid.UUID(account["id"]))
    return AccountRead(
        id=account["id"],
        name=account["name"],
        currency=account["currency"],
        iban=account.get("iban"),
        status=account["status"],
        balance_minor=balance_minor,
        product_type=account.get("product_type", "checking"),
        interest_rate_bps=account.get("interest_rate_bps"),
        term_months=account.get("term_months"),
        maturity_date=account.get("maturity_date"),
        created_at=account["created_at"],
    )


@router.post("", response_model=AccountRead, status_code=201)
async def open_account(
    payload: AccountCreate,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> AccountRead:
    account = await service.open_account(
        supabase,
        user,
        payload.name,
        payload.currency,
        product_type=payload.product_type,
        term_months=payload.term_months,
    )
    return await _to_read_model(supabase, account)


@router.get("", response_model=list[AccountRead])
async def list_accounts(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[AccountRead]:
    accounts = await service.list_accounts(supabase, user)
    return [await _to_read_model(supabase, account) for account in accounts]


@router.get("/products", response_model=AccountProductsRead)
async def get_account_products() -> AccountProductsRead:
    return AccountProductsRead(
        savings_interest_rate_bps=service.SAVINGS_INTEREST_RATE_BPS,
        term_deposit_options=[
            TermDepositOption(term_months=months, interest_rate_bps=rate_bps)
            for months, rate_bps in sorted(service.TERM_DEPOSIT_RATES_BPS.items())
        ],
    )


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
