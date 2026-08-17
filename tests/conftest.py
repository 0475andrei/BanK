"""Shared fixtures.

Every test in this suite is OFFLINE: the mock provider is the only provider used
and no Azure credentials are read or required.
"""

from __future__ import annotations

import pytest

from app.ai.agents.banking_agent import BankingAgent
from app.ai.context import Context
from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas import ModelResponse, ToolCall
from app.ai.service import build_banking_tools
from app.ai.tools.registry import ToolRegistry

# The accounts the test user owns, and one they emphatically do not. Tests use
# UNOWNED_ACCOUNT_ID whenever they play the part of a model trying to widen access.
OWNED_ACCOUNT_IDS = ("acc-owned-1", "acc-owned-2")
UNOWNED_ACCOUNT_ID = "acc-someone-else-9"
TEST_USER_ID = "user-under-test"


@pytest.fixture
def context() -> Context:
    """A trusted identity, as the edge would build it."""
    return Context(user_id=TEST_USER_ID, account_ids=OWNED_ACCOUNT_IDS)


@pytest.fixture
def tools() -> ToolRegistry:
    return build_banking_tools()


@pytest.fixture
def make_agent(tools: ToolRegistry):
    """Build a BankingAgent over a scripted mock provider."""

    def _make(
        script: list[ModelResponse],
        *,
        repeat_last: bool = False,
        max_iterations: int = 5,
    ) -> tuple[BankingAgent, MockProvider]:
        provider = MockProvider(script, repeat_last=repeat_last)
        agent = BankingAgent(provider, tools, max_iterations=max_iterations)
        return agent, provider

    return _make


def balance_call(account_id: str | None = None, call_id: str = "call-1") -> ToolCall:
    """A get_balance tool call, optionally naming an account.

    Passing no account_id is the normal case now: the tool resolves the account
    from the Context instead.
    """
    arguments = {} if account_id is None else {"account_id": account_id}
    return ToolCall(id=call_id, name="get_balance", arguments=arguments)
