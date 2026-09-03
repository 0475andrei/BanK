"""Bug 2b DIAGNOSTIC (Step 16 Priority 2, item 8) - NOT part of the test suite.

Measures how often InsightsAgent calls `handoff_to_agent` on N repeats of the
exact same message, against the REAL Azure OpenAI deployment. This is not a
pass/fail test: the handoff decision is entirely model discretion (see
insights_agent.py's "CÂND SĂ PREDAI CONVERSAȚIA" guidance and
tool_loop.py::ToolLoopAgent.run), so there is no "correct" count to assert -
only a distribution to look at before deciding whether the prompt needs
tightening.

Why this hits the real provider rather than MockProvider: MockProvider replays
a scripted response, so it cannot vary between runs by construction. The
question this script answers - how much does the model's OWN sampling vary
on identical input - only has an answer if the model actually runs N times.

Why the data layer is faked despite that: every insights tool funnels through
app.ai.tools.insights._shared.load_rows, which (outside statement mode) calls
transactions_service.list_user_transactions_in_range_for_owner. Patching that
one function to return a fixed, plausible set of food-category transactions
means all N runs see IDENTICAL data - so any variance observed below is
attributable to the model's own sampling, not to different numbers landing in
front of it on different runs. Everything else is real and unmodified: the
real AzureOpenAIProvider, InsightsAgent's real system prompt, and the real
tool schemas from build_insights_tools.

Usage (from backend/, with AZURE_OPENAI_* configured in .env):
    python -m scripts.diagnose_handoff_variance [N]

N defaults to 20.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from app.ai.agents.insights_agent import InsightsAgent
from app.ai.context import Context
from app.ai.providers.azure_provider import AzureOpenAIProvider
from app.ai.schemas import Message
from app.ai.service import build_insights_tools
from app.modules.ledger.models import LedgerDirection
from app.modules.transactions.schemas import TransactionEntryRead

MESSAGE = "am cheltuit luna asta pe mâncare și care este soldul meu curent?"
DEFAULT_N = 20

DIAGNOSTIC_USER_ID = "diagnostic-user"
DIAGNOSTIC_ACCOUNT_IDS = ("acc-diagnostic-1",)

# Fixed and hand-picked, not random: the same four food-category debits on
# every run (see module docstring for why identical data matters here).
_FAKE_TRANSACTIONS = [
    TransactionEntryRead(
        id=uuid.uuid4(),
        journal_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        direction=LedgerDirection.DEBIT,
        amount_minor=amount_minor,
        currency="RON",
        description=description,
        reference=description,
        created_at=datetime(2026, 8, day, 12, 0, tzinfo=UTC),
    )
    for day, amount_minor, description in [
        (3, 8500, "Kaufland"),
        (10, 4200, "Mega Image"),
        (17, 12000, "Restaurant Trattoria"),
        (24, 6300, "Carrefour"),
    ]
]


async def _fake_list_transactions(*_args: object, **_kwargs: object) -> list[TransactionEntryRead]:
    return list(_FAKE_TRANSACTIONS)


async def _run_once(agent: InsightsAgent, context: Context) -> tuple[bool, str | None]:
    result = await agent.run([Message(role="user", content=MESSAGE)], context)
    if result.handoff is not None:
        return True, result.handoff.target_agent
    return False, None


async def main(n: int) -> None:
    provider = AzureOpenAIProvider()
    # `supabase=None`: every call the tools would make against it is patched
    # away below, so nothing ever dereferences it.
    tools = build_insights_tools(None, provider)  # type: ignore[arg-type]
    agent = InsightsAgent(provider, tools)
    context = Context(user_id=DIAGNOSTIC_USER_ID, account_ids=DIAGNOSTIC_ACCOUNT_IDS)

    handoff_count = 0
    targets: list[str] = []

    with patch(
        "app.modules.transactions.service.list_user_transactions_in_range_for_owner",
        _fake_list_transactions,
    ):
        for i in range(1, n + 1):
            requested, target = await _run_once(agent, context)
            handoff_count += int(requested)
            targets.append(target or "-")
            print(f"run {i:2d}/{n}: handoff_requested={requested!s:<5} target={target}")

    print()
    print(f"handoff requested: {handoff_count}/{n}")
    print(f"targets seen: {targets}")


if __name__ == "__main__":
    # DEBUG on the tool loop only, to see the Bug 2b log line
    # (tool_loop.py: "agent=%s iteration=%d handoff_requested=%s target=%s")
    # fire alongside this script's own per-run summary, as a cross-check.
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.ai.agents.tool_loop").setLevel(logging.DEBUG)

    requested_n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N
    asyncio.run(main(requested_n))
