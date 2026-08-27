"""Transfers are strictly between two accounts owned by the SAME user (e.g.
Checking -> Savings). Sending money to someone else's account is the
beneficiaries/payments flow (a separate module) - the spec lists "Transfer
money between accounts" and "Send money to saved payees" as two distinct
capabilities, and this module only implements the former.

create_transfer calls the `create_transfer` Postgres RPC directly (see
backend/supabase/migrations/0002_ledger_functions.sql) rather than calling
ledger.post_transaction() and then inserting a `transfers` row as two
separate steps - that composition needs to be atomic, and the RPC already
does both inside one transaction.
"""

import uuid

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.exceptions import (
    CurrencyMismatchError,
    IdempotencyKeyConflictError,
    NotFoundError,
    ValidationError,
)
from app.db.supabase_client import map_postgrest_error
from app.modules.accounts import service as accounts_service
from app.modules.face_auth import service as face_auth_service
from app.modules.notifications import service as notifications_service
from app.modules.transfers.schemas import TransferCreate
from app.modules.users.schemas import UserRead


async def _find_by_idempotency_key(supabase: AsyncClient, idempotency_key: str) -> dict | None:
    resp = (
        await supabase.table("transfers")
        .select("*")
        .eq("idempotency_key", idempotency_key)
        .maybe_single()
        .execute()
    )
    return resp.data if resp is not None else None


async def _is_owned_by(supabase: AsyncClient, account_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    resp = (
        await supabase.table("accounts")
        .select("id")
        .eq("id", str(account_id))
        .eq("user_id", str(user_id))
        .maybe_single()
        .execute()
    )
    return resp is not None and resp.data is not None


async def create_transfer(
    supabase: AsyncClient,
    user: UserRead,
    payload: TransferCreate,
    idempotency_key: str,
    face_token: str | None = None,
    proposal_pre_authorized: bool = False,
) -> dict:
    existing = await _find_by_idempotency_key(supabase, idempotency_key)
    if existing is not None:
        if not await _is_owned_by(supabase, uuid.UUID(existing["from_account_id"]), user.id):
            raise IdempotencyKeyConflictError()
        return existing

    if payload.from_account_id == payload.to_account_id:
        raise ValidationError("from_account_id and to_account_id must differ.")

    from_account = await accounts_service.get_account(supabase, user, payload.from_account_id)
    to_account = await accounts_service.get_account(supabase, user, payload.to_account_id)
    accounts_service.assert_not_locked_for_debit(from_account)

    currency = payload.currency.upper()
    if from_account["currency"] != currency or to_account["currency"] != currency:
        raise CurrencyMismatchError("Transfer currency must match both accounts' currency.")

    # proposal_pre_authorized=True: identity already verified by the proposal
    # confirmation flow (face token or password). Only set by proposals_service.
    # Existing callers (transfers/router.py) never set this flag.
    if not proposal_pre_authorized:
        await face_auth_service.enforce_face_confirmation(
            supabase,
            user,
            required=face_auth_service.requires_face_confirmation(payload.amount_minor),
            token=face_token,
        )

    try:
        resp = await supabase.rpc(
            "create_transfer",
            {
                "p_from_account_id": str(from_account["id"]),
                "p_to_account_id": str(to_account["id"]),
                "p_amount_minor": payload.amount_minor,
                "p_currency": currency,
                "p_description": payload.description
                or f"Transfer: {from_account['name']} → {to_account['name']}",
                "p_idempotency_key": idempotency_key,
                "p_actor_user_id": str(user.id),
            },
        ).execute()
    except APIError as exc:
        mapped = map_postgrest_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise

    # Same category payments/service.py uses for "you got paid" - a
    # transfer moves money into an account just as much as a payment does,
    # so it gets the same real-time pop-up/animation on the frontend (see
    # notifications/bus.py). Always this user's own notification (transfers
    # are strictly own-account-to-own-account - see this module's docstring),
    # not a cross-user event like the payments one.
    await notifications_service.create_notification(
        supabase,
        user.id,
        title="Ai primit bani",
        body=(
            f"{payload.amount_minor / 100:.2f} {currency} au fost transferați din "
            f"\"{from_account['name']}\" în \"{to_account['name']}\"."
        ),
        category="money_received",
    )

    return resp.data


async def get_transfer(supabase: AsyncClient, user: UserRead, transfer_id: uuid.UUID) -> dict:
    resp = (
        await supabase.table("transfers")
        .select("*")
        .eq("id", str(transfer_id))
        .maybe_single()
        .execute()
    )
    transfer = resp.data if resp is not None else None
    if transfer is None or not await _is_owned_by(
        supabase, uuid.UUID(transfer["from_account_id"]), user.id
    ):
        raise NotFoundError("Transfer not found.")
    return transfer


async def list_transfers_for_owner(
    supabase: AsyncClient, user_id: uuid.UUID | str, *, limit: int | None = None
) -> list[dict]:
    """Transfer list for callers holding a bare user id (the AI layer's
    `Context`), mirroring `accounts_service.get_account_for_owner`.

    `limit` is optional so `list_transfers` below - the banking modules' entry
    point - keeps returning the full history unchanged.
    """
    # Safe two-call fallback instead of relying on PostgREST's embedded-
    # filter syntax (unstable across versions) - not a hot/concurrent path.
    accounts_resp = (
        await supabase.table("accounts").select("id").eq("user_id", str(user_id)).execute()
    )
    account_ids = [row["id"] for row in accounts_resp.data]
    if not account_ids:
        return []

    query = (
        supabase.table("transfers")
        .select("*")
        .in_("from_account_id", account_ids)
        .order("created_at", desc=True)
    )
    if limit is not None:
        query = query.limit(limit)

    resp = await query.execute()
    return resp.data


async def list_transfers(supabase: AsyncClient, user: UserRead) -> list[dict]:
    return await list_transfers_for_owner(supabase, user.id)
