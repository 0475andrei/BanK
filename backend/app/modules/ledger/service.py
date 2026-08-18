"""ledger.post_transaction() - the ONLY money-writer in the system. Every
money movement (transfers here; payments/cards/scheduled_transfers/
round_ups in [B]'s modules) must go through this function and nothing else.

Concurrency-safety and idempotency approach:
1. Lock every distinct account referenced by the legs, ONE AT A TIME, in a
   fixed global order (sorted by id), via `SELECT ... FOR UPDATE`, before
   reading or writing anything. Locking one row per statement (rather than
   a single multi-row `WHERE id IN (...) FOR UPDATE`) is what actually
   guarantees lock-acquisition order matches the sort order - that's what
   prevents a deadlock between two journals referencing the same two
   accounts in opposite order (concurrent transfers A->B and B->A).
   Because this function is the only writer, and always locks accounts
   before touching their ledger_entries, two concurrent post_transaction()
   calls that touch the same account are fully serialized by Postgres.
2. Re-check the idempotency key AFTER acquiring the locks (not just
   before) - double-checked locking. A request that raced another one for
   the same account(s) will, by the time it gets the lock, see the first
   request's committed journal and short-circuit into a replay instead of
   double-posting.
3. As a last line of defence for the case where two concurrent requests
   share an idempotency key but DON'T share any locked account (so neither
   serializes the other), journal_transactions.idempotency_key has a
   DB-level UNIQUE constraint. The loser's flush raises IntegrityError,
   caught here and turned into a replay too.

This function flushes but deliberately does NOT commit - the caller's
request-scoped session (core/dependencies.py::get_db) commits once at the
end of the request, so locks are held for the full business transaction,
not just this function call.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.core.exceptions import (
    AccountClosedError,
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidLedgerLegsError,
)
from app.core.money import ensure_positive_minor
from app.modules.accounts.models import Account, AccountStatus
from app.modules.ledger.models import JournalTransaction, LedgerDirection, LedgerEntry
from app.modules.ledger.schemas import LedgerLeg


async def _find_by_idempotency_key(
    db: AsyncSession, idempotency_key: str
) -> JournalTransaction | None:
    stmt = select(JournalTransaction).where(JournalTransaction.idempotency_key == idempotency_key)
    return (await db.execute(stmt)).scalar_one_or_none()


def _validate_legs(legs: Sequence[LedgerLeg]) -> None:
    if len(legs) < 2:
        raise InvalidLedgerLegsError("A journal needs at least two legs.")

    currencies = {leg.currency.upper() for leg in legs}
    if len(currencies) > 1:
        raise CurrencyMismatchError(
            "All legs of one journal must share a currency; cross-currency "
            "movements are out of scope."
        )

    for leg in legs:
        ensure_positive_minor(leg.amount_minor, field="leg.amount_minor")

    debits = sum(leg.amount_minor for leg in legs if leg.direction == LedgerDirection.DEBIT)
    credits = sum(leg.amount_minor for leg in legs if leg.direction == LedgerDirection.CREDIT)
    if debits != credits:
        raise InvalidLedgerLegsError(f"Unbalanced journal: debits={debits} != credits={credits}.")


async def _lock_accounts(
    db: AsyncSession, account_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, Account]:
    ordered_ids = sorted(set(account_ids), key=str)
    locked: dict[uuid.UUID, Account] = {}

    for account_id in ordered_ids:
        stmt = select(Account).where(Account.id == account_id).with_for_update()
        account = (await db.execute(stmt)).scalar_one_or_none()
        if account is None:
            raise AccountNotFoundError(f"Account {account_id} not found.")
        if account.status != AccountStatus.ACTIVE:
            raise AccountClosedError(f"Account {account_id} is closed.")
        locked[account_id] = account

    return locked


async def get_balance(db: AsyncSession, account_id: uuid.UUID) -> int:
    """Balance = SUM(credits) - SUM(debits) for this account, always
    computed fresh from ledger_entries. Called from inside post_transaction
    the account is already locked, so this read is consistent with any
    concurrent writer; called standalone (e.g. GET /accounts) it's a plain
    read-committed snapshot, which is fine for display purposes."""
    stmt = select(LedgerEntry.direction, LedgerEntry.amount_minor).where(
        LedgerEntry.account_id == account_id
    )
    rows = (await db.execute(stmt)).all()
    balance = 0
    for direction, amount_minor in rows:
        if direction == LedgerDirection.CREDIT:
            balance += amount_minor
        else:
            balance -= amount_minor
    return balance


async def post_transaction(
    db: AsyncSession,
    legs: Sequence[LedgerLeg],
    idempotency_key: str,
    description: str,
    *,
    reference: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> JournalTransaction:
    _validate_legs(legs)

    account_ids = [leg.account_id for leg in legs]
    locked_accounts = await _lock_accounts(db, account_ids)

    # Double-checked: re-read now that we hold the locks, so a request that
    # raced us for the same account(s) and lost sees our committed result
    # instead of double-posting.
    existing = await _find_by_idempotency_key(db, idempotency_key)
    if existing is not None:
        return existing

    for leg in legs:
        account = locked_accounts[leg.account_id]
        if account.currency.upper() != leg.currency.upper():
            raise CurrencyMismatchError(
                f"Account {account.id} is {account.currency}, leg is {leg.currency}."
            )
        if leg.direction == LedgerDirection.DEBIT:
            balance = await get_balance(db, account.id)
            if balance < leg.amount_minor:
                raise InsufficientFundsError(
                    f"Account {account.id} has insufficient funds for this debit."
                )

    journal = JournalTransaction(
        reference=reference or uuid.uuid4().hex[:12].upper(),
        idempotency_key=idempotency_key,
        description=description,
    )

    try:
        async with db.begin_nested():
            db.add(journal)
            await db.flush()  # surfaces the UNIQUE(idempotency_key) race here

            for leg in legs:
                db.add(
                    LedgerEntry(
                        journal_id=journal.id,
                        account_id=leg.account_id,
                        direction=leg.direction,
                        amount_minor=leg.amount_minor,
                        currency=leg.currency.upper(),
                    )
                )
            await db.flush()
    except IntegrityError:
        # Lost the race: another transaction committed a journal with this
        # idempotency_key between our check above and our INSERT (it must
        # not have overlapped on locked accounts, or we'd have blocked on
        # the row lock instead). Their result is the canonical one.
        db.expunge(journal)
        existing = await _find_by_idempotency_key(db, idempotency_key)
        if existing is None:
            raise
        return existing

    await record_audit_event(
        db,
        user_id=actor_user_id,
        action="ledger.post_transaction",
        entity=f"journal_transactions:{journal.id}",
        metadata={
            "idempotency_key": idempotency_key,
            "legs": [
                {
                    "account_id": str(leg.account_id),
                    "direction": leg.direction.value,
                    "amount_minor": leg.amount_minor,
                    "currency": leg.currency,
                }
                for leg in legs
            ],
        },
    )

    return journal
