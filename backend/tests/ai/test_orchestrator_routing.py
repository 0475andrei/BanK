"""Context-first document routing (Step 12): an active document forces
DocumentAgent regardless of what the message says - see
Orchestrator.route()'s docstring for why keyword rules must not run first
while a document is attached.

Offline, same as tests/ai/test_routing.py.
"""

from __future__ import annotations

from app.ai.agents.banking_agent import BankingAgent
from app.ai.agents.document_agent import DocumentAgent
from app.ai.context import Context
from app.ai.orchestrator import Orchestrator
from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas import ModelResponse
from app.ai.service import build_banking_tools, build_document_tools
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
