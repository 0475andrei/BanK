import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounts import service as accounts_service
from app.modules.ledger.models import JournalTransaction, LedgerEntry
from app.modules.transactions.schemas import TransactionEntryRead
from app.modules.users.models import User

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def list_account_transactions(
    db: AsyncSession,
    user: User,
    account_id: uuid.UUID,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> list[TransactionEntryRead]:
    # Ownership check - raises AccountNotFoundError (404) if this isn't the
    # caller's account, without leaking whether it exists at all.
    await accounts_service.get_account(db, user, account_id)

    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    stmt = (
        select(LedgerEntry, JournalTransaction.description, JournalTransaction.reference)
        .join(JournalTransaction, JournalTransaction.id == LedgerEntry.journal_id)
        .where(LedgerEntry.account_id == account_id)
    )
    if date_from is not None:
        stmt = stmt.where(LedgerEntry.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(LedgerEntry.created_at <= date_to)

    stmt = stmt.order_by(LedgerEntry.created_at.desc()).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).all()
    return [
        TransactionEntryRead(
            id=entry.id,
            journal_id=entry.journal_id,
            account_id=entry.account_id,
            direction=entry.direction,
            amount_minor=entry.amount_minor,
            currency=entry.currency,
            description=description,
            reference=reference,
            created_at=entry.created_at,
        )
        for entry, description, reference in rows
    ]
