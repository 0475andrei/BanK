"""Payments move money between accounts owned by DIFFERENT users, found by
IBAN - the counterpart to transfers.py's same-user-only movement (see that
module's docstring). create_payment calls the `create_payment` Postgres RPC
(backend/supabase/migrations/0005_...sql), which wraps post_transaction()
the same way create_transfer does. A successful payment also upserts a
beneficiary/contact for the sender (see beneficiaries/service.py) - not
atomic with the money movement (a separate REST call), same accepted
limitation as audit_log writes post-Supabase-migration.
"""

import uuid

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.exceptions import (
    CurrencyMismatchError,
    IbanNotFoundError,
    IdempotencyKeyConflictError,
    ValidationError,
)
from app.db.supabase_client import map_postgrest_error
from app.modules.accounts import service as accounts_service
from app.modules.auth.validation import validate_iban
from app.modules.beneficiaries import service as beneficiaries_service
from app.modules.face_auth import service as face_auth_service
from app.modules.payments.schemas import PaymentCreate
from app.modules.users.schemas import UserRead


async def _find_by_idempotency_key(supabase: AsyncClient, idempotency_key: str) -> dict | None:
    resp = (
        await supabase.table("payments")
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


async def _get_account_by_iban(supabase: AsyncClient, iban: str) -> dict:
    resp = await supabase.table("accounts").select("*").eq("iban", iban).maybe_single().execute()
    account = resp.data if resp is not None else None
    if account is None:
        raise IbanNotFoundError()
    return account


async def create_payment(
    supabase: AsyncClient,
    user: UserRead,
    payload: PaymentCreate,
    idempotency_key: str,
    face_token: str | None = None,
) -> dict:
    existing = await _find_by_idempotency_key(supabase, idempotency_key)
    if existing is not None:
        if not await _is_owned_by(supabase, uuid.UUID(existing["from_account_id"]), user.id):
            raise IdempotencyKeyConflictError()
        return existing

    to_iban = payload.to_iban.replace(" ", "").upper()
    if not validate_iban(to_iban):
        raise ValidationError("Invalid IBAN.")

    from_account = await accounts_service.get_account(supabase, user, payload.from_account_id)
    accounts_service.assert_not_locked_for_debit(from_account)
    to_account = await _get_account_by_iban(supabase, to_iban)

    if to_account["id"] == str(from_account["id"]):
        raise ValidationError("Cannot send a payment to the same account.")

    currency = from_account["currency"]
    if to_account["currency"] != currency:
        raise CurrencyMismatchError(
            "Payments can't cross currencies - sender and recipient accounts must "
            "share one."
        )

    await face_auth_service.enforce_face_confirmation(supabase, user, payload.amount_minor, face_token)

    try:
        resp = await supabase.rpc(
            "create_payment",
            {
                "p_from_account_id": str(from_account["id"]),
                "p_to_account_id": str(to_account["id"]),
                "p_to_iban": to_iban,
                "p_amount_minor": payload.amount_minor,
                "p_currency": currency,
                "p_description": payload.description
                or f"Plată către {payload.beneficiary_name}",
                "p_idempotency_key": idempotency_key,
                "p_actor_user_id": str(user.id),
            },
        ).execute()
    except APIError as exc:
        mapped = map_postgrest_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise

    payment = resp.data

    await beneficiaries_service.upsert_beneficiary(
        supabase, user_id=user.id, iban=to_iban, display_name=payload.beneficiary_name
    )

    return payment


async def list_payments(supabase: AsyncClient, user: UserRead) -> list[dict]:
    # Safe two-call fallback instead of relying on PostgREST's embedded-
    # filter syntax (unstable across versions) - not a hot/concurrent path.
    accounts_resp = (
        await supabase.table("accounts").select("id").eq("user_id", str(user.id)).execute()
    )
    account_ids = [row["id"] for row in accounts_resp.data]
    if not account_ids:
        return []

    resp = (
        await supabase.table("payments")
        .select("*")
        .in_("from_account_id", account_ids)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data
