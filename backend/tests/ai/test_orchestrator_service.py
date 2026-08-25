"""Orchestrator routing and the AIService end-to-end path (mock provider only)."""

from __future__ import annotations

import pytest

from app.ai.agents.banking_agent import BankingAgent
from app.ai.agents.insights_agent import InsightsAgent
from app.ai.agents.planning_agent import PlanningAgent
from app.ai.orchestrator import Orchestrator
from app.ai.providers.mock_embedding_provider import MockEmbeddingProvider
from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas import Message, ModelResponse
from app.ai.service import (
    AIService,
    build_banking_tools,
    build_insights_tools,
    build_planning_tools,
)
from tests.ai.conftest import OWNED_ACCOUNT_IDS, FakeSupabase, balance_call


def _service(script: list[ModelResponse]) -> tuple[AIService, MockProvider]:
    provider = MockProvider(script)
    return (
        AIService(FakeSupabase(), provider=provider, embedding_provider=MockEmbeddingProvider()),
        provider,
    )


def test_route_always_returns_the_banking_agent(context):
    """5a. With one agent registered, every message resolves to it - whether a
    rule matched it or not."""
    provider = MockProvider([ModelResponse(text="ok")])
    agent = BankingAgent(provider, build_banking_tools(FakeSupabase()))
    orchestrator = Orchestrator([agent])

    for message in ["what's my balance?", "hello", ""]:
        decision = orchestrator.route(message, context)
        assert decision.agent_name == "banking"
        assert orchestrator.get(decision.agent_name) is agent


def test_service_wires_a_default_orchestrator_with_all_agents(context):
    """Insights is registered FIRST (it wins shared keywords with Banking),
    Documents goes right after Insights (its position barely matters - see
    _build_orchestrator's docstring - since the context-first check in
    Orchestrator.route() bypasses registration order whenever a document is
    active), Docs is registered next (it wins Banking's `cont` stem for
    documentation questions like "ce comision are contul curent"),
    Planning is registered LAST (it loses the shared `econom` keyword to
    Banking), Banking is the default (it takes anything unclaimed). All of
    those are different things."""
    service, _ = _service([ModelResponse(text="ok")])

    assert service.orchestrator.names() == [
        "insights",
        "documents",
        "docs",
        "banking",
        "planning",
    ]

    # A banking-only keyword still reaches banking despite insights being first.
    decision = service.orchestrator.route("care este soldul meu?", context)
    assert isinstance(service.orchestrator.get(decision.agent_name), BankingAgent)


async def test_dispatch_routes_and_runs_with_the_context(context):
    provider = MockProvider([ModelResponse(text="routed")])
    orchestrator = Orchestrator([BankingAgent(provider, build_banking_tools(FakeSupabase()))])

    reply, trace, routing = await orchestrator.dispatch(
        [Message(role="user", content="hi")], "hi", context
    )

    assert reply == "routed"
    assert trace == []
    assert routing.agent_name == "banking"


async def test_service_handle_message_end_to_end_with_tool_call(context):
    """5b. AIService -> orchestrator -> agent -> tool -> final reply."""
    service, provider = _service(
        [
            ModelResponse(tool_calls=[balance_call()]),
            ModelResponse(text="You have $123.45."),
        ]
    )

    reply, history, _ = await service.handle_message([], "what's my balance?", context)

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
    # Both messages carry a banking keyword so routing resolves by rule. With
    # two agents registered, a message matching NO rule would spend a provider
    # call on classification first - which would consume this script and make
    # the test about routing instead of about history.
    service, provider = _service(
        [ModelResponse(text="first"), ModelResponse(text="second")]
    )

    _, history, _ = await service.handle_message([], "soldul one", context)
    reply, history, _ = await service.handle_message(history, "soldul two", context)

    assert reply == "second"
    assert [m.role for m in history] == ["user", "assistant", "user", "assistant"]

    # The second provider call saw the whole prior conversation.
    second_turn = [m for m in provider.calls[1] if m.role != "system"]
    assert [m.content for m in second_turn] == ["soldul one", "first", "soldul two"]


async def test_service_does_not_mutate_the_history_it_was_given(context):
    service, _ = _service([ModelResponse(text="hi")])
    history: list[Message] = []

    # Rule-matching message: keeps the single scripted response for the agent
    # rather than spending it on the routing classifier (see the note in
    # test_service_threads_history_across_turns).
    await service.handle_message(history, "care e soldul", context)

    assert history == []


async def test_handle_message_requires_a_context():
    """Identity has no default: omitting it is an error, not a silent fallback."""
    service, _ = _service([ModelResponse(text="hi")])

    with pytest.raises(TypeError):
        await service.handle_message([], "hello")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Two agents: the first time routing has a real choice to make.
# ---------------------------------------------------------------------------


def _two_agent_orchestrator(classifier_script: list[ModelResponse] | None = None):
    """Both agents wired exactly as AIService wires them: insights first (it
    wins shared keywords), banking default."""
    provider = MockProvider([ModelResponse(text="ok")], repeat_last=True)
    classifier = (
        MockProvider(classifier_script) if classifier_script is not None else None
    )
    orchestrator = Orchestrator(provider=classifier)
    orchestrator.register(InsightsAgent(provider, build_insights_tools(FakeSupabase())))
    orchestrator.register(
        BankingAgent(provider, build_banking_tools(FakeSupabase())), default=True
    )
    return orchestrator


def test_routing_picks_banking_for_transactional_question(context):
    decision = _two_agent_orchestrator().route("care este soldul?", context)

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_keywords"


def test_routing_picks_insights_for_analytical_question(context):
    """`cheltui` and `bani` belong to BOTH agents; insights is registered first
    so the analytical reading wins."""
    decision = _two_agent_orchestrator().route("unde am cheltuit banii?", context)

    assert decision.agent_name == "insights"
    assert decision.matched_rule == "insights_spending"


def test_routing_picks_insights_for_spending_keyword(context):
    decision = _two_agent_orchestrator().route("cât am cheltuit pe mâncare?", context)

    assert decision.agent_name == "insights"
    assert decision.matched_rule == "insights_spending"


def test_routing_picks_insights_for_english_analytical(context):
    decision = _two_agent_orchestrator().route("show me my spending patterns", context)

    assert decision.agent_name == "insights"
    assert decision.matched_rule == "insights_spending"


def test_routing_ambiguous_falls_back_to_default_via_llm(context):
    """Matches neither rule set -> the classifier decides, and it can pick the
    non-default agent."""
    orchestrator = _two_agent_orchestrator([ModelResponse(text="insights")])

    decision = orchestrator.route("ce mai faci?", context)

    assert decision.agent_name == "insights"
    assert decision.matched_rule is None
    assert decision.confidence == 0.7


def test_routing_ambiguous_llm_returns_invalid_name_falls_back_to_default(context):
    orchestrator = _two_agent_orchestrator([ModelResponse(text="gibberish")])

    decision = orchestrator.route("ce mai faci?", context)

    assert decision.agent_name == "banking"  # the default
    assert decision.matched_rule is None
    assert "unknown agent" in decision.reason


def test_time_slice_keywords_pull_time_scoped_questions_into_insights(context):
    """DOCUMENTED CONSEQUENCE of the insights_time_slice rule plus registration
    order: a time-scoped banking question routes to insights, because `luna`
    is checked before banking's `tranzac`.

    Defensible - the analytical agent can read transactions over a range - but
    it is the main tuning candidate if it proves wrong in practice. Pinned here
    so a future change to the rules shows up as a deliberate decision rather
    than a surprise.
    """
    decision = _two_agent_orchestrator().route("ce tranzacții am avut luna asta?", context)

    assert decision.agent_name == "insights"
    assert decision.matched_rule == "insights_time_slice"


def test_person_named_andrei_does_not_route_to_insights(context):
    """Regression: an `an` stem would prefix-match "Andrei" and send a transfer
    request to the analytics agent. `anul` is used instead."""
    orchestrator = _two_agent_orchestrator([ModelResponse(text="banking")])

    decision = orchestrator.route("trimite 50 RON către Andrei", context)

    assert decision.agent_name == "banking"
    # No rule claimed it, so this went through the classifier - which is the
    # honest outcome: "trimite" is not a keyword either agent declares.
    assert decision.matched_rule is None


def test_insights_agent_registered_with_orchestrator():
    orchestrator = _two_agent_orchestrator()

    assert "insights" in orchestrator.names()
    assert isinstance(orchestrator.get("insights"), InsightsAgent)


def test_insights_agent_has_own_routing_rules():
    assert InsightsAgent.routing_rules
    assert InsightsAgent.routing_rules is not BankingAgent.routing_rules
    assert {rule.name for rule in InsightsAgent.routing_rules} == {
        "insights_spending",
        "insights_analysis",
        "insights_categories",
        "insights_time_slice",
    }


def test_insights_agent_has_own_system_prompt():
    """Analytical, not transactional - and explicitly still read-only."""
    prompt = InsightsAgent.system_prompt

    assert prompt != BankingAgent.system_prompt
    assert "asistentul analitic" in prompt
    assert "Ai voie să interpretezi" in prompt
    # Cannot act, and must not claim to have acted.
    assert "NU poți efectua acțiuni" in prompt
    assert "niciodată să nu pretinzi că ai făcut-o" in prompt
    assert "NU inventa cifre" in prompt


def test_insights_agent_gets_only_its_own_tools():
    """An agent's reach is what it was handed: the analytical agent has no way
    to read card numbers."""
    tools = build_insights_tools(FakeSupabase())

    assert tools.names() == [
        "get_transactions_in_range",
        "categorize_transactions",
        "detect_recurring_payments",
        "compute_spending_stats",
        "detect_anomalies",
        "compare_statement_to_ledger",
    ]
    assert tools.get("list_cards") is None
    assert all(tool.read_only for tool in tools)


def test_orchestrator_rejects_duplicate_agent_names():
    provider = MockProvider([ModelResponse(text="ok")])
    orchestrator = Orchestrator([BankingAgent(provider, build_banking_tools(FakeSupabase()))])

    with pytest.raises(ValueError):
        orchestrator.register(BankingAgent(provider, build_banking_tools(FakeSupabase())))


# ---------------------------------------------------------------------------
# Three agents: PlanningAgent joins, registered exactly as AIService wires it.
# ---------------------------------------------------------------------------


def _three_agent_orchestrator(classifier_script: list[ModelResponse] | None = None):
    """All three agents wired exactly as AIService wires them: insights
    first (wins shared keywords with banking), banking default, planning
    last (loses the shared `econom` keyword to banking - see PlanningAgent's
    KNOWN COLLISION note)."""
    provider = MockProvider([ModelResponse(text="ok")], repeat_last=True)
    classifier = (
        MockProvider(classifier_script) if classifier_script is not None else None
    )
    orchestrator = Orchestrator(provider=classifier)
    orchestrator.register(InsightsAgent(provider, build_insights_tools(FakeSupabase())))
    orchestrator.register(
        BankingAgent(provider, build_banking_tools(FakeSupabase())), default=True
    )
    orchestrator.register(PlanningAgent(provider, build_planning_tools(FakeSupabase())))
    return orchestrator


def test_routing_picks_planning_for_goal_question(context):
    """Uses the `obiectiv` keyword directly, not `econom` - which collides
    with Banking's "Economii" account keyword and loses to it (registered
    first); see test_routing_economii_collision_goes_to_banking below."""
    decision = _three_agent_orchestrator().route(
        "vreau să-mi ating obiectivul de a-mi lua un PS5", context
    )

    assert decision.agent_name == "planning"
    assert decision.matched_rule == "planning_goals"


def test_routing_picks_planning_for_projection(context):
    """Avoids `sold` (a Banking keyword, checked first) - "proiecție
    financiară" only matches Planning's `proiect` stem."""
    decision = _three_agent_orchestrator().route("poți face o proiecție financiară?", context)

    assert decision.agent_name == "planning"
    assert decision.matched_rule == "planning_projection"


def test_routing_picks_planning_for_what_if(context):
    """Avoids `cheltui` (shared by Insights and Banking, both checked before
    Planning) - "dacă aș reduce cafeaua" only matches Planning's `daca` stem."""
    decision = _three_agent_orchestrator().route("ce-ar fi dacă aș reduce cafeaua?", context)

    assert decision.agent_name == "planning"
    assert decision.matched_rule == "planning_scenario"


def test_routing_still_picks_banking_for_balance(context):
    decision = _three_agent_orchestrator().route("care este soldul?", context)

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_keywords"


def test_routing_still_picks_insights_for_spending(context):
    decision = _three_agent_orchestrator().route("unde am cheltuit banii?", context)

    assert decision.agent_name == "insights"
    assert decision.matched_rule == "insights_spending"


def test_routing_economii_collision_goes_to_banking(context):
    """DOCUMENTED COLLISION: `econom` belongs to both Banking ("Economii"
    account) and Planning (savings goals). Banking is registered first among
    the two, so a bare "economii" phrasing goes to Banking - see
    PlanningAgent's KNOWN COLLISION note. Pinned here so a future rule change
    shows up as a deliberate decision, same as the existing `luna`/insights
    and `an`/Andrei regression tests above."""
    decision = _three_agent_orchestrator().route("arată-mi contul de economii", context)

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_keywords"


def test_planning_agent_registered_with_orchestrator():
    orchestrator = _three_agent_orchestrator()

    assert "planning" in orchestrator.names()
    assert isinstance(orchestrator.get("planning"), PlanningAgent)


def test_planning_agent_has_own_routing_rules():
    assert PlanningAgent.routing_rules
    assert PlanningAgent.routing_rules is not BankingAgent.routing_rules
    assert PlanningAgent.routing_rules is not InsightsAgent.routing_rules
    assert {rule.name for rule in PlanningAgent.routing_rules} == {
        "planning_goals",
        "planning_projection",
        "planning_scenario",
        "planning_timeline",
        "planning_budget",
    }


def test_planning_agent_has_own_system_prompt():
    """Goal-oriented, not transactional or analytical - and explicitly still
    read-only, same shape as the other two agents' guardrail assertions."""
    prompt = PlanningAgent.system_prompt

    assert prompt != BankingAgent.system_prompt
    assert prompt != InsightsAgent.system_prompt
    assert "planificatorul financiar" in prompt
    assert "orientat pe obiective" in prompt
    assert "NU poți executa nimic" in prompt


def test_planning_agent_gets_only_its_own_tools():
    """An agent's reach is what it was handed: the planning agent has no way
    to read card numbers or categorize spending."""
    tools = build_planning_tools(FakeSupabase())

    assert tools.names() == ["project_balance", "simulate_scenario", "savings_goal"]
    assert tools.get("list_cards") is None
    assert tools.get("categorize_transactions") is None
    assert all(tool.read_only for tool in tools)


