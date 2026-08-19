"""ledger.post_transaction() - the ONLY money-writer in the system. Every
money movement (transfers here; payments/cards/scheduled_transfers/
round_ups elsewhere) must go through this function and nothing else.

The locking/idempotency/atomicity logic now lives in Postgres, not here -
see backend/supabase/migrations/0002_ledger_functions.sql::post_transaction.
PostgREST runs each RPC call inside one real transaction, which is the only
way to keep SELECT...FOR UPDATE row locks held across the
lock -> check -> insert sequence this needs; that can't be done from
separate REST calls. This module is a thin wrapper: build the legs JSON,
call the RPC, map Postgres errors back to the same typed exceptions callers
already expect.
"""

import uuid
from collections.abc import Sequence

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.exceptions import CurrencyMismatchError, InvalidLedgerLegsError
from app.core.money import ensure_positive_minor
from app.db.supabase_client import map_postgrest_error
from app.modules.ledger.models import LedgerDirection
from app.modules.ledger.schemas import LedgerLeg


def _validate_legs(legs: Sequence[LedgerLeg]) -> None:
    """Fail-fast client-side pre-check - cheap, avoids a network round trip
    for obviously-bad input. The RPC function re-validates all of this
    server-side too; that's the real enforcement boundary now."""
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


async def get_balance(supabase: AsyncClient, account_id: uuid.UUID) -> int:
    """Balance = SUM(credits) - SUM(debits) for this account, computed
    server-side (see get_account_balance in the RPC migration)."""
    resp = await supabase.rpc("get_account_balance", {"p_account_id": str(account_id)}).execute()
    return resp.data


async def post_transaction(
    supabase: AsyncClient,
    legs: Sequence[LedgerLeg],
    idempotency_key: str,
    description: str,
    *,
    reference: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> dict:
    _validate_legs(legs)

    params = {
        "p_idempotency_key": idempotency_key,
        "p_description": description,
        "p_legs": [
            {
                "account_id": str(leg.account_id),
                "direction": leg.direction.value,
                "amount_minor": leg.amount_minor,
                "currency": leg.currency.upper(),
            }
            for leg in legs
        ],
        "p_reference": reference,
        "p_actor_user_id": str(actor_user_id) if actor_user_id else None,
    }

    try:
        resp = await supabase.rpc("post_transaction", params).execute()
    except APIError as exc:
        mapped = map_postgrest_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise

    return resp.data
