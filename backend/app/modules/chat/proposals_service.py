"""AI-proposed write actions: create, confirm (with step-up auth), reject.

The AI layer never executes a write directly (see app/ai/tools/propose_tools.py
and the `read_only` flag on app/ai/tools/base.py::Tool) - a propose_* tool only
ever inserts a `pending` row here. Only `confirm_proposal`, after verifying the
caller's step-up credential SERVER-SIDE, calls the real service function
(create_transfer, create_payment, open_account, close_account, cancel_card).

THE RULE, same as everywhere else identity/auth is involved: never trust the
frontend's "the user proved who they are" - the password is checked against
the bcrypt hash here, and the face token was only ever issued by a prior
server-side 1:1 face match (see face_auth_service.create_face_confirmation).
`credential` (whichever kind it is) must never be logged, and must never end
up in the `proposals` row - it is used once, in memory, and discarded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.exceptions import (
    NotFoundError,
    ProposalExpiredError,
    ProposalNotPendingError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import verify_password
from app.modules.accounts.service import close_account, open_account
from app.modules.cards.service import cancel_card
from app.modules.face_auth import service as face_auth_service
from app.modules.payments.schemas import PaymentCreate
from app.modules.payments.service import create_payment
from app.modules.transfers.schemas import TransferCreate
from app.modules.transfers.service import create_transfer
from app.modules.users.schemas import UserRead
from supabase import AsyncClient

#: A pending proposal past this age is treated as expired at the next
#: confirm/reject attempt (lazy expiry - no background job, same pattern as
#: auth/service.py's password-reset codes).
PROPOSAL_EXPIRY_MINUTES = 10


async def create_proposal(
    supabase: AsyncClient,
    *,
    user_id: str,
    conversation_id: str,
    proposal_type: str,
    payload: dict[str, Any],
    summary: str,
) -> dict:
    resp = (
        await supabase.table("proposals")
        .insert(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "proposal_type": proposal_type,
                "payload": payload,
                "summary": summary,
            }
        )
        .execute()
    )
    return resp.data[0]


async def get_proposal(supabase: AsyncClient, user: UserRead, proposal_id: str) -> dict:
    """Ownership-checked read. A missing id and one owned by someone else look
    identical to the caller - NotFoundError either way, never 403, so a
    non-owner can't confirm a proposal exists by the error shape alone."""
    resp = (
        await supabase.table("proposals").select("*").eq("id", proposal_id).maybe_single().execute()
    )
    proposal = resp.data if resp is not None else None
    if proposal is None or proposal["user_id"] != str(user.id):
        raise NotFoundError("Proposal not found.")
    return proposal


async def confirm_proposal(
    supabase: AsyncClient,
    user: UserRead,
    proposal_id: str,
    auth_method: str,
    credential: str,
) -> dict:
    proposal = await get_proposal(supabase, user, proposal_id)

    # Status gate - prevents double-execution on a double-click or a replayed
    # request. Checked BEFORE expiry so an already-decided proposal reports
    # its real state rather than "expired" if it happens to also be old.
    if proposal["status"] != "pending":
        raise ProposalNotPendingError()

    created_at = datetime.fromisoformat(proposal["created_at"])
    if datetime.now(UTC) - created_at > timedelta(minutes=PROPOSAL_EXPIRY_MINUTES):
        await (
            supabase.table("proposals")
            .update({"status": "expired", "rejected_at": datetime.now(UTC).isoformat()})
            .eq("id", proposal["id"])
            .execute()
        )
        raise ProposalExpiredError()

    # THE critical security gate. Only reached with a still-pending, not-yet-
    # expired proposal; only past this point does anything real execute.
    if auth_method == "face":
        if not await face_auth_service.has_face_enrolled(supabase, user):
            raise ValidationError("Autentificarea facială nu este activată pe acest cont.")
        await face_auth_service.consume_face_confirmation_token(supabase, user, credential)
    elif auth_method == "password":
        resp = (
            await supabase.table("users")
            .select("password_hash")
            .eq("id", str(user.id))
            .maybe_single()
            .execute()
        )
        password_hash = resp.data["password_hash"] if resp is not None and resp.data else None
        if password_hash is None or not verify_password(credential, password_hash):
            raise UnauthorizedError("Parolă incorectă.")
    else:
        raise ValidationError("Metodă de autentificare necunoscută.")

    result = await _execute(supabase, user, proposal)

    updated = (
        await supabase.table("proposals")
        .update(
            {
                "status": "confirmed",
                "confirmed_at": datetime.now(UTC).isoformat(),
                "result": result,
            }
        )
        .eq("id", proposal["id"])
        .execute()
    )
    return updated.data[0]


async def reject_proposal(supabase: AsyncClient, user: UserRead, proposal_id: str) -> dict:
    proposal = await get_proposal(supabase, user, proposal_id)
    if proposal["status"] != "pending":
        raise ProposalNotPendingError()

    updated = (
        await supabase.table("proposals")
        .update({"status": "rejected", "rejected_at": datetime.now(UTC).isoformat()})
        .eq("id", proposal["id"])
        .execute()
    )
    return updated.data[0]


async def _execute(supabase: AsyncClient, user: UserRead, proposal: dict) -> dict:
    """Dispatch on proposal_type. Each branch calls the REAL service function,
    with `proposal_pre_authorized=True` where that parameter exists - the
    step-up check above already stood in for the amount/new-recipient face
    check those functions would otherwise perform themselves.

    The proposal's own id is the idempotency key: a proposal is confirmed at
    most once (the status gate in confirm_proposal enforces that), so it is
    already a natural, stable, unique key for the underlying write - no
    separate key generation needed."""
    proposal_type = proposal["proposal_type"]
    payload = proposal["payload"]
    idempotency_key = str(proposal["id"])

    if proposal_type == "transfer":
        transfer_payload = TransferCreate(
            from_account_id=payload["from_account_id"],
            to_account_id=payload["to_account_id"],
            amount_minor=payload["amount_minor"],
            currency=payload["currency"],
            description=payload.get("description"),
        )
        return await create_transfer(
            supabase, user, transfer_payload, idempotency_key, proposal_pre_authorized=True
        )

    if proposal_type == "payment":
        payment_payload = PaymentCreate(
            from_account_id=payload["from_account_id"],
            to_iban=payload["to_iban"],
            beneficiary_name=payload["beneficiary_name"],
            amount_minor=payload["amount_minor"],
            description=payload.get("description"),
            save_beneficiary=payload.get("save_beneficiary", True),
        )
        return await create_payment(
            supabase, user, payment_payload, idempotency_key, proposal_pre_authorized=True
        )

    if proposal_type == "open_account":
        return await open_account(
            supabase,
            user,
            payload["name"],
            payload["currency"],
            product_type=payload.get("product_type", "checking"),
            term_months=payload.get("term_months"),
        )

    if proposal_type == "close_account":
        return await close_account(supabase, user, uuid.UUID(payload["account_id"]))

    if proposal_type == "cancel_card":
        return await cancel_card(supabase, user, uuid.UUID(payload["card_id"]))

    raise ValueError(f"Unknown proposal_type: {proposal_type!r}")
