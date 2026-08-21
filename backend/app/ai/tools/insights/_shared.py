"""Shared plumbing for the insights tools that analyze transaction history.

Every tool in this package follows the same shape: resolve a date window,
fetch the relevant ledger entries (all of the user's accounts, or one if
`account_id` narrows it), then compute something over them. Keeping the fetch
here means the account-scoping / ownership rule only has to be gotten right
once, instead of once per tool.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from app.ai.context import Context

if TYPE_CHECKING:
    from supabase import AsyncClient

    from app.modules.transactions.schemas import TransactionEntryRead


def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """Inclusive whole-day UTC bounds - same convention as get_transactions_in_range."""
    return (
        datetime.combine(start, time.min, tzinfo=UTC),
        datetime.combine(end, time.max, tzinfo=UTC),
    )


def months_ago(reference: datetime, months: int) -> datetime:
    """Calendar-correct "N months before `reference`", not a 30-day approximation.

    Clamps the day of month so e.g. Mar 31 minus 1 month lands on Feb 28/29
    instead of overflowing into March.
    """
    month_index = reference.month - 1 - months
    year = reference.year + month_index // 12
    month = month_index % 12 + 1
    day = min(reference.day, calendar.monthrange(year, month)[1])
    return reference.replace(year=year, month=month, day=day)


async def fetch_entries(
    supabase: AsyncClient,
    context: Context,
    *,
    date_from: datetime,
    date_to: datetime,
    account_id: str | None = None,
) -> list[TransactionEntryRead]:
    """Every ledger entry in the window - one account if named, else all of them.

    `account_id` is untrusted model input: `context.resolve_account` is the
    only thing allowed to accept or refuse it. Unlike `Context.resolve_account`
    used elsewhere, `None` here means "every account", not "the default
    account" - these are cross-account analytical reads by default.
    """
    from app.modules.transactions import service as transactions_service

    if account_id is not None:
        resolved = context.resolve_account(account_id)
        return await transactions_service.list_account_transactions_for_owner(
            supabase,
            context.user_id,
            uuid.UUID(resolved),
            date_from=date_from,
            date_to=date_to,
            limit=transactions_service.ANALYTICS_MAX_LIMIT,
        )

    return await transactions_service.list_user_transactions_in_range_for_owner(
        supabase,
        context.user_id,
        date_from=date_from,
        date_to=date_to,
        limit=transactions_service.ANALYTICS_MAX_LIMIT,
    )
