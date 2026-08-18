"""STUB balance tool.

!!! PLACEHOLDER — replace with the real ledger read tool later. !!!

Person A owns `modules/ledger`; it does not exist yet, so this returns a fixed
fake balance and touches no DB.

What is NOT a stub here is the identity path: the account is resolved through
the trusted `Context`, never from the model's arguments. The model may name an
account only to NARROW the selection to one the user already owns; anything else
is refused. That check must survive into the real version.

When the real version lands it must:
  * derive the balance as SUM(ledger_entries), never read a stored balance;
  * keep resolving the account via `context.resolve_account(...)` before it
    queries anything.
Money stays in integer minor units — no floats, ever.
"""

from __future__ import annotations

import logging
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.ai.context import Context, IdentityError
from app.ai.schemas import ToolResult
from app.ai.tools.base import Tool

logger = logging.getLogger(__name__)

# Fixed stub figures. 12345 minor units = 123.45 USD.
_STUB_BALANCE_MINOR = 12345
_STUB_CURRENCY = "USD"

AccountId = Annotated[str, StringConstraints(min_length=1)]


class GetBalanceInput(BaseModel):
    """Arguments the model may supply. Validated, but still untrusted.

    `account_id` is optional and can only narrow: it is honoured when the
    context user owns it and refused otherwise. Omitting it selects the user's
    default account.
    """

    account_id: AccountId | None = Field(
        default=None,
        description=(
            "Optional. One of the user's own account identifiers. "
            "Omit it to use their default account — you do not need to know or "
            "guess account identifiers."
        ),
    )


class GetBalanceTool(Tool):
    name = "get_balance"
    description = (
        "Read the current balance of one of the signed-in user's accounts. "
        "Returns an integer amount in minor units (e.g. cents) plus the currency. "
        "The user's identity is supplied by the application, not by you."
    )
    input_schema = GetBalanceInput
    read_only = True

    def run(self, validated_input: BaseModel, context: Context) -> ToolResult:
        assert isinstance(validated_input, GetBalanceInput)

        try:
            # The ONLY place the account is decided. Untrusted input in, trusted
            # account out — or a refusal.
            account_id = context.resolve_account(validated_input.account_id)
        except IdentityError:
            # Log the refusal itself; never the identifier that was refused.
            logger.warning(
                "access denied user_id=%s tool=%s", context.user_id, self.name
            )
            raise

        # STUB: no ledger, no DB. Real figures arrive with A's ledger module.
        return ToolResult(
            name=self.name,
            data={
                "account_id": account_id,
                "balance_minor": _STUB_BALANCE_MINOR,
                "currency": _STUB_CURRENCY,
                "source": "stub",
            },
        )
