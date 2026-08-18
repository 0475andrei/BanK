import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.core.exceptions import AccountNotEmptyError, AccountNotFoundError, ValidationError
from app.modules.accounts.models import Account, AccountStatus
from app.modules.ledger import service as ledger_service
from app.modules.users.models import User


def _validate_currency(currency: str) -> str:
    currency = currency.upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValidationError(f"Currency must be a 3-letter code, got: {currency!r}")
    return currency


async def open_account(db: AsyncSession, user: User, name: str, currency: str) -> Account:
    currency = _validate_currency(currency)

    account = Account(user_id=user.id, name=name, currency=currency, status=AccountStatus.ACTIVE)
    db.add(account)
    await db.flush()

    await record_audit_event(
        db,
        user_id=user.id,
        action="accounts.open",
        entity=f"accounts:{account.id}",
        metadata={"name": name, "currency": currency},
    )
    return account


async def _get_owned_account(db: AsyncSession, user: User, account_id: uuid.UUID) -> Account:
    stmt = select(Account).where(Account.id == account_id, Account.user_id == user.id)
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is None:
        # Same error whether the account doesn't exist or just isn't the
        # caller's - don't leak which one it is.
        raise AccountNotFoundError()
    return account


async def get_account(db: AsyncSession, user: User, account_id: uuid.UUID) -> Account:
    return await _get_owned_account(db, user, account_id)


async def list_accounts(db: AsyncSession, user: User) -> list[Account]:
    stmt = select(Account).where(Account.user_id == user.id).order_by(Account.created_at)
    return list((await db.execute(stmt)).scalars().all())


async def get_account_balance(db: AsyncSession, user: User, account_id: uuid.UUID) -> int:
    """Ownership-checked balance read. [B]'s AI read tools (get_balance)
    and any other module should call this rather than reaching into
    ledger.service directly, so ownership is always enforced."""
    account = await _get_owned_account(db, user, account_id)
    return await ledger_service.get_balance(db, account.id)


async def close_account(db: AsyncSession, user: User, account_id: uuid.UUID) -> Account:
    account = await _get_owned_account(db, user, account_id)
    if account.status == AccountStatus.CLOSED:
        return account

    balance = await ledger_service.get_balance(db, account.id)
    if balance != 0:
        raise AccountNotEmptyError()

    account.status = AccountStatus.CLOSED
    await db.flush()

    await record_audit_event(
        db, user_id=user.id, action="accounts.close", entity=f"accounts:{account.id}"
    )
    return account
