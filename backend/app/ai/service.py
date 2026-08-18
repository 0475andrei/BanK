"""AIService — the single entry point into the AI layer.

Wires provider -> tools -> agent -> orchestrator. The future `/chat` endpoint
calls `handle_message` and nothing else.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.ai.agents.banking_agent import BankingAgent
from app.ai.context import Context
from app.ai.orchestrator import Orchestrator
from app.ai.providers.base import ModelProvider
from app.ai.schemas import Message
from app.ai.tools.banking import GetBalanceTool
from app.ai.tools.registry import ToolRegistry


def build_banking_tools() -> ToolRegistry:
    """The read-only tools the banking agent is allowed to call.

    STUB tools only for now — see `tools/banking/get_balance.py`.
    """
    return ToolRegistry([GetBalanceTool()])


class AIService:
    """Holds the orchestrator and hands conversations to the routed agent."""

    def __init__(
        self,
        provider: ModelProvider | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        # Real provider by default; tests inject the mock.
        if provider is None:
            from app.ai.providers.azure_provider import AzureOpenAIProvider

            provider = AzureOpenAIProvider()
        self._provider = provider
        self._orchestrator = orchestrator or Orchestrator(
            [BankingAgent(provider, build_banking_tools())]
        )

    @property
    def orchestrator(self) -> Orchestrator:
        return self._orchestrator

    def handle_message(
        self,
        history: Sequence[Message],
        user_message: str,
        context: Context,
    ) -> tuple[str, list[Message]]:
        """Answer `user_message` for the user identified by `context`.

        `context` is required and has no default on purpose: forgetting to pass
        an identity must be an error, never a silent fallback to some ambient
        one. Callers build it at the edge (see `app.ai.context`).

        Returns the reply plus the updated history. History is in-memory only —
        persistence to the `conversations` / `messages` tables comes later.
        """
        conversation = [*history, Message(role="user", content=user_message)]
        reply = self._orchestrator.dispatch(conversation, user_message, context)
        return reply, [*conversation, Message(role="assistant", content=reply)]
