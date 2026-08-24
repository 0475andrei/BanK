"""Offline contract tests for the propose_* tools (Step 11).

Same spirit as test_tools.py: input-schema validation and access-denied
refusals never touch the database (Tool.execute validates before `run()`
runs, and `Context.resolve_account`/`owns` are pure in-memory checks), so
these run against the offline `FakeSupabase`. The real create_proposal
insert + confirm/reject/execute flow is covered in
tests/integration/test_propose_tools.py and test_proposals_confirm.py.
"""

from __future__ import annotations

from app.ai.context import Context
from app.ai.schemas import ToolCall
from app.ai.tools.propose_tools import (
    PROPOSE_TOOL_NAMES,
    ProposeCancelCardTool,
    ProposeCloseAccountTool,
    ProposeOpenAccountTool,
    ProposePaymentTool,
    ProposeTransferTool,
)
from app.ai.tools.registry import ToolRegistry
from tests.ai.conftest import OWNED_ACCOUNT_IDS, UNOWNED_ACCOUNT_ID

ALL_PROPOSE_TOOL_CLASSES = (
    ProposeTransferTool,
    ProposePaymentTool,
    ProposeOpenAccountTool,
    ProposeCloseAccountTool,
    ProposeCancelCardTool,
)


def test_propose_tool_names_match_the_module_constant():
    assert {cls.name for cls in ALL_PROPOSE_TOOL_CLASSES} == set(PROPOSE_TOOL_NAMES)


def test_every_propose_tool_is_write_adjacent(supabase):
    for cls in ALL_PROPOSE_TOOL_CLASSES:
        assert cls(supabase).read_only is False


def test_every_propose_tool_advertises_a_usable_spec(supabase):
    registry = ToolRegistry([cls(supabase) for cls in ALL_PROPOSE_TOOL_CLASSES])

    for spec in registry.list_specs():
        assert spec["type"] == "function"
        assert spec["function"]["name"]
        assert spec["function"]["description"]
        assert spec["function"]["parameters"]["type"] == "object"


async def test_propose_transfer_rejects_non_positive_amount(context, supabase):
    result = await ProposeTransferTool(supabase).execute(
        ToolCall(
            id="c1",
            name="propose_transfer",
            arguments={
                "from_account_id": OWNED_ACCOUNT_IDS[0],
                "to_account_id": OWNED_ACCOUNT_IDS[1],
                "amount_minor": 0,
                "currency": "RON",
            },
        ),
        context,
    )
    assert result.ok is False
    assert "invalid input" in (result.error or "")


async def test_propose_transfer_refuses_an_account_the_user_does_not_own(context, supabase):
    """SECURITY: the model naming someone else's account id must never reach
    the DB - `context.resolve_account` refuses before propose_tools.py's
    `_resolve_owned_account` issues any query, and the refusal never echoes
    the refused id (see IdentityError's docstring)."""
    result = await ProposeTransferTool(supabase).execute(
        ToolCall(
            id="c1",
            name="propose_transfer",
            arguments={
                "from_account_id": UNOWNED_ACCOUNT_ID,
                "to_account_id": OWNED_ACCOUNT_IDS[1],
                "amount_minor": 10_000,
                "currency": "RON",
            },
        ),
        context,
    )
    assert result.ok is False
    assert "access denied" in (result.error or "")
    assert UNOWNED_ACCOUNT_ID not in (result.error or "")


async def test_propose_close_account_refuses_an_account_the_user_does_not_own(context, supabase):
    result = await ProposeCloseAccountTool(supabase).execute(
        ToolCall(
            id="c1",
            name="propose_close_account",
            arguments={"account_id": UNOWNED_ACCOUNT_ID},
        ),
        context,
    )
    assert result.ok is False
    assert "access denied" in (result.error or "")


async def test_propose_open_account_requires_term_months_for_term_deposit(context, supabase):
    result = await ProposeOpenAccountTool(supabase).execute(
        ToolCall(
            id="c1",
            name="propose_open_account",
            arguments={"name": "Depozitul meu", "product_type": "term_deposit"},
        ),
        context,
    )
    assert result.ok is False
    assert "invalid input" in (result.error or "")


async def test_propose_close_account_requires_an_active_conversation():
    """propose_* tools need Context.conversation_id (Step 11's addition to
    Context) to satisfy the proposals.conversation_id NOT NULL FK - a
    Context built with none (e.g. the CLI's dev_context) must fail cleanly
    as a tool error, after the account itself resolves fine, never crashing
    the loop."""

    class _FakeQueryWithName:
        async def execute(self):
            from types import SimpleNamespace

            return SimpleNamespace(
                data={"id": OWNED_ACCOUNT_IDS[0], "name": "Cont Curent", "currency": "RON"}
            )

        def __getattr__(self, _name):
            return lambda *a, **kw: self

    class _FakeSupabaseWithNamedAccount:
        def table(self, *_a, **_kw):
            return _FakeQueryWithName()

    context_without_conversation = Context(user_id="user-under-test", account_ids=OWNED_ACCOUNT_IDS)

    result = await ProposeCloseAccountTool(_FakeSupabaseWithNamedAccount()).execute(
        ToolCall(
            id="c1",
            name="propose_close_account",
            arguments={"account_id": OWNED_ACCOUNT_IDS[0]},
        ),
        context_without_conversation,
    )
    assert result.ok is False
    assert "conversation" in (result.error or "")
