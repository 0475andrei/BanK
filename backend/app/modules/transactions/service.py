import uuid
from datetime import datetime

from supabase import AsyncClient

from app.modules.accounts import service as accounts_service
from app.modules.transactions.schemas import TransactionEntryRead
from app.modules.users.schemas import UserRead

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


async def list_account_transactions(
    supabase: AsyncClient,
    user: UserRead,
    account_id: uuid.UUID,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> list[TransactionEntryRead]:
    # Ownership check - raises AccountNotFoundError (404) if this isn't the
    # caller's account, without leaking whether it exists at all.
    await accounts_service.get_account(supabase, user, account_id)

    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    query = (
        supabase.table("ledger_entries")
        .select("*, journal:journal_transactions(description, reference)")
        .eq("account_id", str(account_id))
    )
    if date_from is not None:
        query = query.gte("created_at", date_from.isoformat())
    if date_to is not None:
        query = query.lte("created_at", date_to.isoformat())

    resp = await query.order("created_at", desc=True).limit(limit).offset(offset).execute()

    return [
        TransactionEntryRead(
            id=row["id"],
            journal_id=row["journal_id"],
            account_id=row["account_id"],
            direction=row["direction"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            description=row["journal"]["description"],
            reference=row["journal"]["reference"],
            created_at=row["created_at"],
        )
        for row in resp.data
    ]
