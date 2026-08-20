"""AIService — the single entry point into the AI layer.

Wires provider -> tools -> agent -> orchestrator. The future `/chat` endpoint
calls `handle_message` and nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.ai.agents.banking_agent import BankingAgent
from app.ai.context import Context
from app.ai.orchestrator import Orchestrator
from app.ai.providers.base import ModelProvider
from app.ai.schemas import Message
from app.ai.tools.banking import GetBalanceTool
from app.ai.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from supabase import AsyncClient


def build_banking_tools(supabase: AsyncClient) -> ToolRegistry:
    """The read-only tools the banking agent is allowed to call.

    `supabase` is handed to every tool that reads data; the tools hold it for
    their lifetime (the client is a stateless HTTP client, safe to share).
    """
    return ToolRegistry([GetBalanceTool(supabase)])


class AIService:
    """Holds the orchestrator and hands conversations to the routed agent."""

    def __init__(
        self,
        supabase: AsyncClient,
        provider: ModelProvider | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        # Real provider by default; tests inject the mock.
        if provider is None:
            from app.ai.providers.azure_provider import AzureOpenAIProvider

            provider = AzureOpenAIProvider()
        self._provider = provider
        self._orchestrator = orchestrator or Orchestrator(
            [BankingAgent(provider, build_banking_tools(supabase))]
        )

    @property
    def orchestrator(self) -> Orchestrator:
        return self._orchestrator

    async def handle_message(
        self,
        history: Sequence[Message],
        user_message: str,
        context: Context,
    ) -> tuple[str, list[Message]]:
        """Answer `user_message` for the user identified by `context`.

        `context` is required and has no default on purpose: forgetting to pass
        an identity must be an error, never a silent fallback to some ambient
        one. Callers build it at the edge (see `app.ai.context`).

        Returns the reply plus the updated history: `history` with the new
        user turn, any tool-call/tool-result trace the agent produced, and the
        final assistant reply appended, in that order. Callers persist this
        (see `app.modules.chat.conversations_service`) so a reload replays the
        same transcript the model actually saw.
        """
        conversation = [*history, Message(role="user", content=user_message)]
        reply, trace = await self._orchestrator.dispatch(conversation, user_message, context)
        return reply, [*conversation, *trace, Message(role="assistant", content=reply)]
