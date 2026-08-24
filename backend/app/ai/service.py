"""AIService — the single entry point into the AI layer.

Wires provider -> tools -> agent -> orchestrator. The future `/chat` endpoint
calls `handle_message` and nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.ai.agents.banking_agent import BankingAgent
from app.ai.agents.docs_agent import DocsAgent
from app.ai.agents.insights_agent import InsightsAgent
from app.ai.agents.planning_agent import PlanningAgent
from app.ai.context import Context
from app.ai.orchestrator import Orchestrator
from app.ai.providers.base import ModelProvider
from app.ai.routing import RoutingDecision
from app.ai.schemas import Message
from app.ai.tools.banking import (
    GetBalanceTool,
    ListAccountsTool,
    ListCardsTool,
    ListTransactionsTool,
    ListTransfersTool,
    ResolveIbanHolderTool,
)
from app.ai.tools.insights import (
    CategorizeTransactionsTool,
    ComputeSpendingStatsTool,
    DetectAnomaliesTool,
    DetectRecurringPaymentsTool,
    GetTransactionsInRangeTool,
)
from app.ai.tools.knowledge import SearchKnowledgeBaseTool
from app.ai.tools.planning import ProjectBalanceTool, SavingsGoalTool, SimulateScenarioTool
from app.ai.tools.propose_tools import (
    ProposeCancelCardTool,
    ProposeCloseAccountTool,
    ProposeOpenAccountTool,
    ProposePaymentTool,
    ProposeTransferTool,
)
from app.ai.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from supabase import AsyncClient

    from app.ai.providers.embedding_base import EmbeddingProvider


def build_banking_tools(supabase: AsyncClient) -> ToolRegistry:
    """The read-only tools the banking agent is allowed to call.

    `supabase` is handed to every tool that reads data; the tools hold it for
    their lifetime (the client is a stateless HTTP client, safe to share).
    """
    return ToolRegistry(
        [
            GetBalanceTool(supabase),
            ListAccountsTool(supabase),
            ListTransactionsTool(supabase),
            ListCardsTool(supabase),
            ListTransfersTool(supabase),
            ResolveIbanHolderTool(supabase),
            # Write-adjacent: each only creates a `pending` proposal row, never
            # executes (see app/ai/tools/propose_tools.py's module docstring).
            ProposeTransferTool(supabase),
            ProposePaymentTool(supabase),
            ProposeOpenAccountTool(supabase),
            ProposeCloseAccountTool(supabase),
            ProposeCancelCardTool(supabase),
        ]
    )


def build_insights_tools(supabase: AsyncClient) -> ToolRegistry:
    """The read-only tools the insights agent is allowed to call.

    Deliberately a different registry from `build_banking_tools`: an agent's
    reach is defined by what it is handed, so the analytical agent cannot read
    card numbers and the banking agent cannot run an unbounded date sweep.
    """
    return ToolRegistry(
        [
            GetTransactionsInRangeTool(supabase),
            CategorizeTransactionsTool(supabase),
            DetectRecurringPaymentsTool(supabase),
            ComputeSpendingStatsTool(supabase),
            DetectAnomaliesTool(supabase),
        ]
    )


def build_planning_tools(supabase: AsyncClient) -> ToolRegistry:
    """The read-only tools the planning agent is allowed to call.

    A third distinct registry, same reason as insights vs banking: the
    goal-oriented agent projects and simulates, it does not need (and is not
    handed) the analytical categorisation/anomaly tools either.
    """
    return ToolRegistry(
        [
            ProjectBalanceTool(supabase),
            SimulateScenarioTool(supabase),
            SavingsGoalTool(supabase),
        ]
    )


def build_docs_tools(
    supabase: AsyncClient, embedding_provider: EmbeddingProvider
) -> ToolRegistry:
    """The docs agent's one tool: semantic search over ingested documentation.

    Unlike the other three registries, this one also needs an embedding
    provider (to embed the query) - the tool holds both.
    """
    return ToolRegistry([SearchKnowledgeBaseTool(supabase, embedding_provider)])


class AIService:
    """Holds the orchestrator and hands conversations to the routed agent."""

    def __init__(
        self,
        supabase: AsyncClient,
        provider: ModelProvider | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        # Real providers by default; tests inject mocks.
        if provider is None:
            from app.ai.providers.azure_provider import AzureOpenAIProvider

            provider = AzureOpenAIProvider()
        if embedding_provider is None:
            from app.ai.providers.azure_embedding_provider import AzureEmbeddingProvider

            embedding_provider = AzureEmbeddingProvider()
        self._provider = provider
        # The provider goes to the orchestrator too: routing's LLM fallback
        # needs a model of its own now that more than one agent is registered.
        self._orchestrator = orchestrator or self._build_orchestrator(
            supabase, provider, embedding_provider
        )

    @staticmethod
    def _build_orchestrator(
        supabase: AsyncClient, provider: ModelProvider, embedding_provider: EmbeddingProvider
    ) -> Orchestrator:
        """Register the agents, in the order routing should consider them.

        ORDER MATTERS. `Orchestrator._match_rules` walks agents in registration
        order and stops at the first rule that claims the message, so the agent
        registered first gets first refusal. Insights goes first deliberately:
        it and Banking share the `cheltui` / `bani` keywords (Banking has had
        them since Step 6), and for a phrase like "cât am cheltuit?" the
        analytical reading is the more specific one.

        Docs goes right after Insights, for the same kind of reason: a message
        like "ce comision are contul curent" contains Banking's `cont` stem
        too, but the more specific reading is "what does the fee schedule say"
        - a documentation question, not a request to read the account's data.

        Planning goes LAST deliberately, for the opposite reason: it shares
        the `econom` stem with Banking's "Economii" account keyword, and here
        Banking should win - "arată-mi contul de economii" is transactional.
        That does mean a bare "econom"-only savings-goal phrasing currently
        mis-routes to Banking (see the KNOWN COLLISION note on
        `PlanningAgent`'s rules); acceptable for now, revisited in Step 16.

        Banking is still the DEFAULT — what an unmatched or unclassifiable
        message falls back to — which is a separate thing from rule order.
        """
        orchestrator = Orchestrator(provider=provider)
        orchestrator.register(InsightsAgent(provider, build_insights_tools(supabase)))
        orchestrator.register(DocsAgent(provider, build_docs_tools(supabase, embedding_provider)))
        orchestrator.register(
            BankingAgent(provider, build_banking_tools(supabase)), default=True
        )
        orchestrator.register(PlanningAgent(provider, build_planning_tools(supabase)))
        return orchestrator

    @property
    def orchestrator(self) -> Orchestrator:
        return self._orchestrator

    async def handle_message(
        self,
        history: Sequence[Message],
        user_message: str,
        context: Context,
    ) -> tuple[str, list[Message], RoutingDecision]:
        """Answer `user_message` for the user identified by `context`.

        `context` is required and has no default on purpose: forgetting to pass
        an identity must be an error, never a silent fallback to some ambient
        one. Callers build it at the edge (see `app.ai.context`).

        Returns `(reply, history, routing)`. `history` is the caller's history
        with the new user turn, any tool-call/tool-result trace the agent
        produced, and the final assistant reply appended, in that order;
        callers persist it (see `app.modules.chat.conversations_service`) so a
        reload replays the same transcript the model actually saw. `routing`
        records which agent answered and why.

        TODO: if this grows past 3 elements, switch to a TurnResult Pydantic
        model rather than widening the tuple again.
        """
        conversation = [*history, Message(role="user", content=user_message)]
        reply, trace, routing = await self._orchestrator.dispatch(
            conversation, user_message, context
        )
        return (
            reply,
            [*conversation, *trace, Message(role="assistant", content=reply)],
            routing,
        )
