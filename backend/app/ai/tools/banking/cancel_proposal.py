"""Cancel a still-pending proposal the user has changed their mind about.

The symmetric counterpart to the propose_* tools (app/ai/tools/propose_tools.py)
that was missing: those only ever create a `pending` row, and until now the
only way to take it back was `POST /proposals/{id}/reject` - a frontend-only
button, never reachable from the conversation itself. A user who says
"anulează" in a LATER message (a different turn, possibly several messages
after the proposal was made) had no way to act on that from chat - see
proposals_service.reject_proposal, which this tool is a thin, ownership-scoped
wrapper around.

Unlike confirm, cancelling needs no step-up auth: it can only ever narrow a
pending proposal to "rejected", never move money or change an account/card, so
there is nothing here for Face ID/password to protect.

SECURITY: `proposal_id` is untrusted model input, same as every other tool
argument. `reject_proposal_for_owner` re-checks ownership against
`context.user_id` server-side (see proposals_service.get_proposal_for_owner) -
naming another user's proposal id, guessed or otherwise, produces the same
"not found" as a nonexistent one, never a 403 that would confirm it exists.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.ai.context import Context
from app.ai.schemas import ToolResult
from app.ai.tools.base import Tool
from app.core.exceptions import NotFoundError, ProposalNotPendingError

if TYPE_CHECKING:
    from supabase import AsyncClient

logger = logging.getLogger(__name__)


class CancelProposalInput(BaseModel):
    proposal_id: str | None = Field(
        default=None,
        description=(
            "Optional. The id of the pending proposal to cancel, if you already "
            "know it from earlier in this conversation. Omit it to cancel the "
            "user's current pending proposal in this conversation - there is "
            "never more than one at a time, so you do not need to have "
            "remembered the exact id."
        ),
    )


class CancelProposalTool(Tool):
    name = "cancel_proposal"
    description = (
        "Anulează (respinge) o propunere aflată încă în așteptare - una pe care "
        "utilizatorul a cerut-o mai devreme în conversație (transfer, plată, "
        "deschidere/închidere cont, anulare card) dar acum s-a răzgândit, chiar "
        "dacă a cerut-o cu multe mesaje în urmă. Foloseşte-o pentru orice cerere "
        "de anulare/renunțare ('anulează', 'nu mai vreau', 'renunț', 'oprește', "
        "'las-o baltă'), nu doar pentru fraza exactă 'anulează propunerea'. Nu "
        "face nimic unei propuneri deja confirmate, deja respinse, sau expirate."
    )
    input_schema = CancelProposalInput
    read_only = False

    def __init__(self, supabase: AsyncClient) -> None:
        self._supabase = supabase

    async def run(self, validated_input: BaseModel, context: Context) -> ToolResult:
        assert isinstance(validated_input, CancelProposalInput)

        from app.modules.chat.proposals_service import (
            get_pending_proposal_for_conversation,
            reject_proposal_for_owner,
        )

        proposal_id = validated_input.proposal_id
        if proposal_id is None:
            if context.conversation_id is None:
                return ToolResult.failure(
                    name=self.name,
                    error="Nu există nicio propunere activă în această conversație.",
                )
            pending = await get_pending_proposal_for_conversation(
                self._supabase, context.user_id, context.conversation_id
            )
            if pending is None:
                return ToolResult.failure(
                    name=self.name,
                    error="Nu există nicio propunere în așteptare de anulat.",
                )
            proposal_id = pending["id"]

        try:
            proposal = await reject_proposal_for_owner(
                self._supabase, context.user_id, proposal_id
            )
        except NotFoundError:
            # Same message whether the id is foreign or simply never existed -
            # never confirms or denies that a proposal with this id exists for
            # someone else. See this module's docstring.
            return ToolResult.failure(
                name=self.name, error="Nu am găsit nicio propunere de anulat cu acel id."
            )
        except ProposalNotPendingError:
            return ToolResult.failure(
                name=self.name,
                error=(
                    "Propunerea aceasta nu mai este în așteptare - a fost deja "
                    "confirmată, respinsă sau a expirat între timp."
                ),
            )

        return ToolResult(
            name=self.name,
            data={"proposal_id": proposal["id"], "status": proposal["status"]},
        )
