"""The agent contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from app.ai.context import Context
from app.ai.routing import RoutingRule
from app.ai.schemas import Message


class Agent(ABC):
    """Turns a conversation into one final assistant reply."""

    #: Stable identifier the orchestrator routes to.
    name: str

    #: What this agent claims. Rules live with the agent that owns them, so
    #: adding an agent means writing its rules in its own file and calling
    #: `orchestrator.register()` — the orchestrator itself never changes.
    #: Empty means "no rule ever matches me"; such an agent is only reachable
    #: via the LLM fallback or by being the default.
    routing_rules: ClassVar[tuple[RoutingRule, ...]] = ()

    @abstractmethod
    async def run(self, messages: Sequence[Message], context: Context) -> tuple[str, list[Message]]:
        """Produce the final reply text. Must not mutate `messages`.

        Returns `(reply, trace)`: `reply` is the final text, and `trace` is
        every message generated while producing it - assistant tool-call
        turns and their tool-result turns, in order, but never the agent's
        own system prompt. `trace` is empty when the model answers directly
        with no tool calls. Callers persist `trace` alongside `reply` so a
        replayed conversation looks the same as it did live.

        `context` is the trusted identity the agent acts for; it is passed to
        every tool and is never derived from the conversation.
        """
        raise NotImplementedError
