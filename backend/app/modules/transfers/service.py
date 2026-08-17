"""Transfers are strictly between two accounts owned by the SAME user (e.g.
Checking -> Savings). Sending money to someone else's account is the
beneficiaries/payments flow ([B]'s module) - the spec lists "Transfer money
between accounts" and "Send money to saved payees" as two distinct
capabilities, and this module only implements the former.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    CurrencyMismatchError,
    IdempotencyKeyConflictError,
    NotFoundError,
    ValidationError,
)
from app.modules.accounts import service as accounts_service
from app.modules.accounts.models import Account
from app.modules.ledger.models import LedgerDirection
from app.modules.ledger.schemas import LedgerLeg
from app.modules.ledger.service import post_transaction
from app.modules.transfers.models import Transfer, TransferStatus
from app.modules.transfers.schemas import TransferCreate
from app.modules.users.models import User


async def _find_by_idempotency_key(db: AsyncSession, idempotency_key: str) -> Transfer | None:
    stmt = select(Transfer).where(Transfer.idempotency_key == idempotency_key)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _find_by_journal(db: AsyncSession, journal_id: uuid.UUID) -> Transfer | None:
    stmt = select(Transfer).where(Transfer.journal_id == journal_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _is_owned_by(db: AsyncSession, account_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    stmt = select(Account.id).where(Account.id == account_id, Account.user_id == user_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def create_transfer(
    db: AsyncSession,
    user: User,
    payload: TransferCreate,
    idempotency_key: str,
) -> Transfer:
    existing = await _find_by_idempotency_key(db, idempotency_key)
    if existing is not None:
        if not await _is_owned_by(db, existing.from_account_id, user.id):
            raise IdempotencyKeyConflictError()
        return existing

    if payload.from_account_id == payload.to_account_id:
        raise ValidationError("from_account_id and to_account_id must differ.")

    from_account = await accounts_service.get_account(db, user, payload.from_account_id)
    to_account = await accounts_service.get_account(db, user, payload.to_account_id)

    currency = payload.currency.upper()
    if from_account.currency != currency or to_account.currency != currency:
        raise CurrencyMismatchError("Transfer currency must match both accounts' currency.")

    legs = [
        LedgerLeg(from_account.id, LedgerDirection.DEBIT, payload.amount_minor, currency),
        LedgerLeg(to_account.id, LedgerDirection.CREDIT, payload.amount_minor, currency),
    ]

    journal = await post_transaction(
        db,
        legs,
        idempotency_key,
        description=payload.description or f"Transfer {from_account.id} -> {to_account.id}",
        actor_user_id=user.id,
    )

    # post_transaction() may have returned an *existing* journal (idempotent
    # replay) - if so there's already a transfers row for it too.
    existing_by_journal = await _find_by_journal(db, journal.id)
    if existing_by_journal is not None:
        return existing_by_journal

    transfer = Transfer(
        journal_id=journal.id,
        from_account_id=from_account.id,
        to_account_id=to_account.id,
        amount_minor=payload.amount_minor,
        currency=currency,
        status=TransferStatus.COMPLETED,
        idempotency_key=idempotency_key,
    )
    db.add(transfer)
    await db.flush()
    return transfer


async def get_transfer(db: AsyncSession, user: User, transfer_id: uuid.UUID) -> Transfer:
    stmt = (
        select(Transfer)
        .join(Account, Account.id == Transfer.from_account_id)
        .where(Transfer.id == transfer_id, Account.user_id == user.id)
    )
    transfer = (await db.execute(stmt)).scalar_one_or_none()
    if transfer is None:
        raise NotFoundError("Transfer not found.")
    return transfer


async def list_transfers(db: AsyncSession, user: User) -> list[Transfer]:
    stmt = (
        select(Transfer)
        .join(Account, Account.id == Transfer.from_account_id)
        .where(Account.user_id == user.id)
        .order_by(Transfer.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())
