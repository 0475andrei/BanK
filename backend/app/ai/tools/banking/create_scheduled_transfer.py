"""Set up a scheduled or recurring transfer between two of the signed-in
user's own accounts.

Write tool - see freeze_card.py's header for why this executes directly
instead of needing a propose/confirm UI step. Reversible: the resulting
schedule can be cancelled with cancel it via the dashboard at any time
before it fires again.

Both accounts are given by id, not name - the model needs to have already
seen them via list_accounts in this conversation (the system prompt says
so). `Context.resolve_account` is still what proves each one is actually
owned by this user; a name typed by the model proves nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from app.ai.context import Context
from app.ai.schemas import ToolResult
from app.ai.tools.base import Tool

if TYPE_CHECKING:
    from supabase import AsyncClient


class CreateScheduledTransferInput(BaseModel):
    from_account_id: str = Field(description="The source account's id (from list_accounts).")
    to_account_id: str = Field(description="The destination account's id (from list_accounts).")
    amount_minor: int = Field(gt=0, description="Amount per transfer, in minor units (e.g. cents).")
    currency: str = Field(min_length=3, max_length=3, description="Must match both accounts.")
    frequency: Literal["weekly", "monthly"] | None = Field(
        default=None,
        description="Omit/null for a single one-time future transfer instead of a recurring one.",
    )
    start_in_days: int = Field(
        default=0,
        ge=0,
        description="Days from now until the first transfer runs. 0 means as soon as possible.",
    )
    description: str | None = Field(default=None, max_length=500)


class CreateScheduledTransferTool(Tool):
    name = "create_scheduled_transfer"
    description = (
        "Schedule a future or recurring transfer between two of the signed-in user's "
        "OWN accounts (not to another person - use a payment for that). Call "
        "list_accounts first if you don't already know the account ids from this "
        "conversation. Confirm the amount, accounts, and frequency with the user "
        "before calling this."
    )
    input_schema = CreateScheduledTransferInput
    read_only = False

    def __init__(self, supabase: AsyncClient) -> None:
        self._supabase = supabase

    async def run(self, validated_input: BaseModel, context: Context) -> ToolResult:
        assert isinstance(validated_input, CreateScheduledTransferInput)
        from app.modules.scheduled_transfers import service as scheduled_transfers_service
        from app.modules.scheduled_transfers.schemas import ScheduledTransferCreate

        from_account_id = context.resolve_account(validated_input.from_account_id)
        to_account_id = context.resolve_account(validated_input.to_account_id)

        payload = ScheduledTransferCreate(
            from_account_id=from_account_id,
            to_account_id=to_account_id,
            amount_minor=validated_input.amount_minor,
            currency=validated_input.currency,
            description=validated_input.description,
            frequency=validated_input.frequency,
            start_at=datetime.now(UTC) + timedelta(days=validated_input.start_in_days),
        )
        row = await scheduled_transfers_service.create_scheduled_transfer_for_owner(
            self._supabase, context.user_id, payload
        )
        return ToolResult(
            name=self.name,
            data={
                "id": row["id"],
                "amount_minor": row["amount_minor"],
                "currency": row["currency"],
                "frequency": row["frequency"],
                "next_run_at": row["next_run_at"],
            },
        )
