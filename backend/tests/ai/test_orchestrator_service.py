"""Orchestrator routing and the AIService end-to-end path (mock provider only)."""

from __future__ import annotations

import pytest

from app.ai.agents.banking_agent import BankingAgent
from app.ai.orchestrator import Orchestrator
from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas import Message, ModelResponse
from app.ai.service import AIService, build_banking_tools
from tests.ai.conftest import OWNED_ACCOUNT_IDS, FakeSupabase, balance_call


def _service(script: list[ModelResponse]) -> tuple[AIService, MockProvider]:
    provider = MockProvider(script)
    return AIService(FakeSupabase(), provider=provider), provider


def test_route_always_returns_the_banking_agent(context):
    """5a. Routing is trivial for now and must resolve to the banking agent."""
    provider = MockProvider([ModelResponse(text="ok")])
    agent = BankingAgent(provider, build_banking_tools(FakeSupabase()))
    orchestrator = Orchestrator([agent])

    for message in ["what's my balance?", "hello", ""]:
        routed = orchestrator.route(message, context)
        assert routed is agent
        assert routed.name == "banking"


def test_service_wires_a_default_orchestrator_with_the_banking_agent(context):
    service, _ = _service([ModelResponse(text="ok")])

    assert service.orchestrator.names() == ["banking"]
    assert isinstance(service.orchestrator.route("anything", context), BankingAgent)


async def test_dispatch_routes_and_runs_with_the_context(context):
    provider = MockProvider([ModelResponse(text="routed")])
    orchestrator = Orchestrator([BankingAgent(provider, build_banking_tools(FakeSupabase()))])

    reply, trace = await orchestrator.dispatch(
        [Message(role="user", content="hi")], "hi", context
    )

    assert reply == "routed"
    assert trace == []


async def test_service_handle_message_end_to_end_with_tool_call(context):
    """5b. AIService -> orchestrator -> agent -> tool -> final reply."""
    service, provider = _service(
        [
            ModelResponse(tool_calls=[balance_call()]),
            ModelResponse(text="You have $123.45."),
        ]
    )

    reply, history = await service.handle_message([], "what's my balance?", context)

    assert reply == "You have $123.45."
    assert provider.call_count == 2

    # Returned history now carries the whole round trip: the user turn, the
    # assistant's tool-call request, the tool result, and the final reply -
    # everything a caller needs to persist and replay the transcript.
    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[0].content == "what's my balance?"
    assert history[1].tool_calls[0].name == "get_balance"
    assert history[2].name == "get_balance"
    assert history[-1].content == "You have $123.45."


async def test_service_reads_the_context_account_end_to_end(context):
    """The account in the tool result came from the Context, not the model."""
    import json

    service, provider = _service(
        [
            ModelResponse(tool_calls=[balance_call()]),
            ModelResponse(text="done"),
        ]
    )

    await service.handle_message([], "balance?", context)

    tool_message = [m for m in provider.calls[1] if m.role == "tool"][0]
    payload = json.loads(tool_message.content or "{}")
    assert payload["result"]["account_id"] == OWNED_ACCOUNT_IDS[0]


async def test_service_threads_history_across_turns(context):
    service, provider = _service(
        [ModelResponse(text="first"), ModelResponse(text="second")]
    )

    _, history = await service.handle_message([], "one", context)
    reply, history = await service.handle_message(history, "two", context)

    assert reply == "second"
    assert [m.role for m in history] == ["user", "assistant", "user", "assistant"]

    # The second provider call saw the whole prior conversation.
    second_turn = [m for m in provider.calls[1] if m.role != "system"]
    assert [m.content for m in second_turn] == ["one", "first", "two"]


async def test_service_does_not_mutate_the_history_it_was_given(context):
    service, _ = _service([ModelResponse(text="hi")])
    history: list[Message] = []

    await service.handle_message(history, "hello", context)

    assert history == []


async def test_handle_message_requires_a_context():
    """Identity has no default: omitting it is an error, not a silent fallback."""
    service, _ = _service([ModelResponse(text="hi")])

    with pytest.raises(TypeError):
        await service.handle_message([], "hello")  # type: ignore[call-arg]


def test_orchestrator_rejects_duplicate_agent_names():
    provider = MockProvider([ModelResponse(text="ok")])
    orchestrator = Orchestrator([BankingAgent(provider, build_banking_tools(FakeSupabase()))])

    with pytest.raises(ValueError):
        orchestrator.register(BankingAgent(provider, build_banking_tools(FakeSupabase())))
