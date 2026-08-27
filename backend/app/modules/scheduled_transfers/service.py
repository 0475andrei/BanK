"""Scheduled/recurring transfers between a user's own accounts.

Same "no cron, execute lazily on read" pattern as savings/term-deposit
interest (see accounts/service.py::accrue_interest_if_due) - a due transfer
runs the next time `run_due_transfers_for_owner` is called (wired into
GET /accounts, see accounts/router.py), not on a background timer. This
keeps the whole app cron-free, consistent with everything else it does that
"happens over time".

Execution deliberately bypasses face_auth's step-up confirmation
(transfers/payments/service.py) - that gate exists for a live human moving
money right now; a scheduled transfer was already authorized by the human
at creation time, and there's no one present to hand a face photo to when
it fires unattended.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import UTC, datetime, timedelta

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.core.exceptions import AppError, CurrencyMismatchError, NotFoundError, ValidationError
from app.db.supabase_client import map_postgrest_error
from app.modules.accounts import service as accounts_service
from app.modules.notifications import service as notifications_service
from app.modules.scheduled_transfers.models import (
    ScheduledTransferFrequency,
    ScheduledTransferStatus,
)
from app.modules.scheduled_transfers.schemas import ScheduledTransferCreate
from app.modules.users.schemas import UserRead

_ACTIVE = ScheduledTransferStatus.ACTIVE.value


def _add_period(reference: datetime, frequency: str) -> datetime:
    """Calendar-correct "one period after `reference`" - mirrors
    accounts/service.py::_add_months's day-clamping for the monthly case
    (Jan 31 + 1 month lands on Feb 28/29, not March)."""
    if frequency == ScheduledTransferFrequency.WEEKLY.value:
        return reference + timedelta(weeks=1)

    month_index = reference.month - 1 + 1
    year = reference.year + month_index // 12
    month = month_index % 12 + 1
    day = min(reference.day, calendar.monthrange(year, month)[1])
    return reference.replace(year=year, month=month, day=day)


async def _validate_and_insert(
    supabase: AsyncClient, user_id: str, payload: ScheduledTransferCreate
) -> dict:
    if payload.from_account_id == payload.to_account_id:
        raise ValidationError("from_account_id and to_account_id must differ.")

    from_account = await accounts_service.get_account_for_owner(
        supabase, user_id, payload.from_account_id
    )
    to_account = await accounts_service.get_account_for_owner(
        supabase, user_id, payload.to_account_id
    )

    currency = payload.currency.upper()
    if from_account["currency"] != currency or to_account["currency"] != currency:
        raise CurrencyMismatchError("Transfer currency must match both accounts' currency.")

    resp = (
        await supabase.table("scheduled_transfers")
        .insert(
            {
                "user_id": user_id,
                "from_account_id": str(payload.from_account_id),
                "to_account_id": str(payload.to_account_id),
                "amount_minor": payload.amount_minor,
                "currency": currency,
                "description": payload.description,
                "frequency": payload.frequency.value if payload.frequency else None,
                "next_run_at": payload.start_at.isoformat(),
                "status": _ACTIVE,
            }
        )
        .execute()
    )
    row = resp.data[0]
    await record_audit_event(
        supabase,
        user_id=uuid.UUID(user_id),
        action="scheduled_transfers.create",
        entity=f"scheduled_transfers:{row['id']}",
        metadata={"frequency": row["frequency"], "amount_minor": row["amount_minor"]},
    )
    return row


async def create_scheduled_transfer(
    supabase: AsyncClient, user: UserRead, payload: ScheduledTransferCreate
) -> dict:
    return await _validate_and_insert(supabase, str(user.id), payload)


async def create_scheduled_transfer_for_owner(
    supabase: AsyncClient, user_id: str, payload: ScheduledTransferCreate
) -> dict:
    return await _validate_and_insert(supabase, user_id, payload)


async def list_scheduled_transfers_for_owner(supabase: AsyncClient, user_id: str) -> list[dict]:
    resp = (
        await supabase.table("scheduled_transfers")
        .select("*")
        .eq("user_id", user_id)
        .order("next_run_at")
        .execute()
    )
    return resp.data


async def list_scheduled_transfers(supabase: AsyncClient, user: UserRead) -> list[dict]:
    return await list_scheduled_transfers_for_owner(supabase, str(user.id))


async def _get_owned(supabase: AsyncClient, user_id: str, scheduled_id: uuid.UUID) -> dict:
    resp = (
        await supabase.table("scheduled_transfers")
        .select("*")
        .eq("id", str(scheduled_id))
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    row = resp.data if resp is not None else None
    if row is None:
        raise NotFoundError("Scheduled transfer not found.")
    return row


async def _set_status(
    supabase: AsyncClient, user_id: str, scheduled_id: uuid.UUID, new_status: str
) -> dict:
    row = await _get_owned(supabase, user_id, scheduled_id)
    if row["status"] in (
        ScheduledTransferStatus.CANCELLED.value,
        ScheduledTransferStatus.COMPLETED.value,
    ):
        raise ValidationError(f"Cannot change a {row['status']} scheduled transfer.")

    if row["status"] != new_status:
        update_resp = (
            await supabase.table("scheduled_transfers")
            .update({"status": new_status})
            .eq("id", str(scheduled_id))
            .execute()
        )
        row = update_resp.data[0]
        await record_audit_event(
            supabase,
            user_id=uuid.UUID(user_id),
            action=f"scheduled_transfers.{new_status}",
            entity=f"scheduled_transfers:{scheduled_id}",
        )
    return row


async def cancel_scheduled_transfer(
    supabase: AsyncClient, user: UserRead, scheduled_id: uuid.UUID
) -> dict:
    return await _set_status(
        supabase, str(user.id), scheduled_id, ScheduledTransferStatus.CANCELLED.value
    )


async def pause_scheduled_transfer(
    supabase: AsyncClient, user: UserRead, scheduled_id: uuid.UUID
) -> dict:
    return await _set_status(
        supabase, str(user.id), scheduled_id, ScheduledTransferStatus.PAUSED.value
    )


async def resume_scheduled_transfer(
    supabase: AsyncClient, user: UserRead, scheduled_id: uuid.UUID
) -> dict:
    return await _set_status(
        supabase, str(user.id), scheduled_id, ScheduledTransferStatus.ACTIVE.value
    )


async def _execute_one(supabase: AsyncClient, row: dict) -> None:
    """Runs a single due transfer and reschedules or completes it.

    Any `AppError` (insufficient funds, closed account, locked term deposit,
    currency mismatch - the account could have changed state since the
    schedule was created) pauses the row with the reason recorded, rather
    than silently retrying forever on every future read or hard-failing the
    caller's GET /accounts."""
    try:
        from_account = await accounts_service.get_account_for_owner(
            supabase, row["user_id"], row["from_account_id"]
        )
        to_account = await accounts_service.get_account_for_owner(
            supabase, row["user_id"], row["to_account_id"]
        )
        accounts_service.assert_not_locked_for_debit(from_account)

        idempotency_key = f"scheduled:{row['id']}:{row['next_run_at']}"
        try:
            await supabase.rpc(
                "create_transfer",
                {
                    "p_from_account_id": str(from_account["id"]),
                    "p_to_account_id": str(to_account["id"]),
                    "p_amount_minor": row["amount_minor"],
                    "p_currency": row["currency"],
                    "p_description": row["description"]
                    or f"Transfer programat: {from_account['name']} → {to_account['name']}",
                    "p_idempotency_key": idempotency_key,
                    "p_actor_user_id": row["user_id"],
                },
            ).execute()
        except APIError as exc:
            mapped = map_postgrest_error(exc)
            raise (mapped or exc) from exc
    except AppError as exc:
        await supabase.table("scheduled_transfers").update(
            {"status": ScheduledTransferStatus.PAUSED.value, "last_error": str(exc)}
        ).eq("id", row["id"]).execute()
        reason = str(exc).rstrip(".")
        await notifications_service.create_notification(
            supabase,
            row["user_id"],
            title="Transfer programat întrerupt",
            body=(
                f"Transferul tău programat a fost pus pe pauză și nu va mai rula "
                f"automat: {reason}. Verifică-l în aplicație."
            ),
        )
        return

    now = datetime.now(UTC)
    if row["frequency"]:
        next_run_at = _add_period(datetime.fromisoformat(row["next_run_at"]), row["frequency"])
        await supabase.table("scheduled_transfers").update(
            {"next_run_at": next_run_at.isoformat(), "last_run_at": now.isoformat(), "last_error": None}
        ).eq("id", row["id"]).execute()
    else:
        await supabase.table("scheduled_transfers").update(
            {
                "status": ScheduledTransferStatus.COMPLETED.value,
                "last_run_at": now.isoformat(),
                "last_error": None,
            }
        ).eq("id", row["id"]).execute()


async def run_due_transfers_for_owner(supabase: AsyncClient, user_id: str) -> None:
    """Called from GET /accounts (see accounts/router.py) before rendering
    balances - the lazy trigger point, same role accrue_interest_if_due
    plays for savings/term-deposit interest."""
    now_iso = datetime.now(UTC).isoformat()
    resp = (
        await supabase.table("scheduled_transfers")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", _ACTIVE)
        .lte("next_run_at", now_iso)
        .execute()
    )
    for row in resp.data:
        await _execute_one(supabase, row)
