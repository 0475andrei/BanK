"""Context-first document routing (Step 12): an active document forces
DocumentAgent regardless of what the message says - see
Orchestrator.route()'s docstring for why keyword rules must not run first
while a document is attached.

Offline, same as tests/ai/test_routing.py.
"""

from __future__ import annotations

from app.ai.agents.banking_agent import BankingAgent
from app.ai.agents.document_agent import DocumentAgent
from app.ai.agents.insights_agent import InsightsAgent
from app.ai.agents.planning_agent import PlanningAgent
from app.ai.context import Context
from app.ai.orchestrator import Orchestrator
from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas import ModelResponse
from app.ai.service import (
    build_banking_tools,
    build_document_tools,
    build_insights_tools,
    build_planning_tools,
)
from tests.ai.conftest import OWNED_ACCOUNT_IDS, TEST_USER_ID, FakeSupabase


def _orchestrator() -> Orchestrator:
    supabase = FakeSupabase()
    banking = BankingAgent(
        MockProvider([ModelResponse(text="ok")], repeat_last=True),
        build_banking_tools(supabase),
    )
    documents = DocumentAgent(
        MockProvider([ModelResponse(text="ok")], repeat_last=True),
        build_document_tools(supabase),
    )
    return Orchestrator([banking, documents])


def test_active_document_overrides_strong_banking_keywords():
    orchestrator = _orchestrator()
    context = Context(
        user_id=TEST_USER_ID,
        account_ids=OWNED_ACCOUNT_IDS,
        active_document_id="doc-1111",
    )

    decision = orchestrator.route("care este soldul meu si ce card am?", context)

    assert decision.agent_name == "documents"
    assert decision.matched_rule == "context_override"
    assert decision.confidence == 1.0


def test_no_active_document_routes_normally():
    """Regression check: without an active document, banking keywords still
    win exactly as they did before Step 12 introduced the context check."""
    orchestrator = _orchestrator()
    context = Context(user_id=TEST_USER_ID, account_ids=OWNED_ACCOUNT_IDS)

    decision = orchestrator.route("care este soldul meu?", context)

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_keywords"


def test_active_statement_overrides_strong_banking_keywords():
    """Step 13's equivalent of test_active_document_overrides_strong_banking_
    keywords above - context.statement_id triggers the same override."""
    orchestrator = _orchestrator()
    context = Context(
        user_id=TEST_USER_ID,
        account_ids=OWNED_ACCOUNT_IDS,
        statement_id="stmt-1111",
    )

    decision = orchestrator.route("care este soldul meu si ce card am?", context)

    assert decision.agent_name == "documents"
    assert decision.matched_rule == "context_override"
    assert decision.reason == "active_statement_in_context"


# ---------------------------------------------------------------------------
# `econom` / `cheltui` two-token collision rules (Step 16 Priority 2, item 7)
#
# Registered in the same relative order as AIService.__init__ - insights,
# then banking, then planning - since that order is what decides which of
# two agents claiming the same stem wins.
# ---------------------------------------------------------------------------


def _collision_orchestrator() -> Orchestrator:
    supabase = FakeSupabase()
    provider = MockProvider([ModelResponse(text="ok")], repeat_last=True)
    insights = InsightsAgent(provider, build_insights_tools(supabase, provider))
    banking = BankingAgent(provider, build_banking_tools(supabase))
    planning = PlanningAgent(provider, build_planning_tools(supabase))
    return Orchestrator([insights, banking, planning])


def _collision_context() -> Context:
    return Context(user_id=TEST_USER_ID, account_ids=OWNED_ACCOUNT_IDS)


def test_econom_with_a_forward_marker_routes_to_planning():
    orchestrator = _collision_orchestrator()

    decision = orchestrator.route(
        "cat ar trebui sa economisesc pentru vacanta", _collision_context()
    )

    assert decision.agent_name == "planning"
    assert decision.matched_rule == "planning_savings_goal"


def test_econom_with_no_forward_marker_still_falls_through_to_banking():
    """Past tense, no forward-looking marker - not a goal, so this must keep
    landing on Banking exactly as it did before the collision rules split."""
    orchestrator = _collision_orchestrator()

    decision = orchestrator.route("am economisit 500 lei", _collision_context())

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_savings_default"


def test_cheltui_with_an_analytical_marker_routes_to_insights():
    orchestrator = _collision_orchestrator()

    decision = orchestrator.route(
        "unde am cheltuit cei mai multi bani", _collision_context()
    )

    assert decision.agent_name == "insights"
    assert decision.matched_rule == "insights_spending_analysis"


def test_cheltui_with_no_analytical_marker_falls_through_to_banking():
    """A plain statement of fact, not an analytical question - falls through
    to Banking's unconditional `cheltui`, unchanged from before this rule."""
    orchestrator = _collision_orchestrator()

    decision = orchestrator.route("am cheltuit 50 lei pe cafea", _collision_context())

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_keywords"


def test_sold_routes_to_banking_unchanged():
    orchestrator = _collision_orchestrator()

    decision = orchestrator.route("care e soldul meu", _collision_context())

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_keywords"


def test_bani_routes_to_banking_unchanged():
    orchestrator = _collision_orchestrator()

    decision = orchestrator.route("cati bani am", _collision_context())

    assert decision.agent_name == "banking"
    assert decision.matched_rule == "banking_keywords"
