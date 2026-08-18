"""Routes an incoming message to the agent that should handle it.

Today there is one agent and routing is trivial. The shape is deliberate: adding
a second agent means `register()`-ing it and extending `route()`, not rewriting
callers — `route()` returns an `Agent`, and that stays true.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.ai.agents.base import Agent
from app.ai.context import Context
from app.ai.schemas import Message

logger = logging.getLogger(__name__)


class Orchestrator:
    """Holds the registered agents and picks one per message."""

    def __init__(self, agents: list[Agent] | None = None, *, default: str | None = None) -> None:
        self._agents: dict[str, Agent] = {}
        # `register` consults `_default`, so it must exist first.
        self._default: str | None = None
        for agent in agents or ():
            self.register(agent)
        if default is not None:
            if default not in self._agents:
                raise ValueError(f"Unknown default agent: {default}")
            self._default = default

    def register(self, agent: Agent, *, default: bool = False) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agent already registered: {agent.name}")
        self._agents[agent.name] = agent
        if default or self._default is None:
            self._default = agent.name

    def get(self, name: str) -> Agent | None:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return list(self._agents)

    def route(self, message: str, context: Context) -> Agent:
        """Pick the agent for this message.

        Step 2: always the default (banking) agent. `context` is accepted so
        that identity-aware routing (product tier, entitlements) can be added
        without changing this signature again. Real intent-based routing
        replaces the body of this method and nothing else.
        """
        del message, context  # not consulted yet
        if self._default is None:
            raise RuntimeError("Orchestrator has no agents registered")
        return self._agents[self._default]

    def dispatch(
        self,
        messages: Sequence[Message],
        user_message: str,
        context: Context,
    ) -> str:
        """Route, then run the chosen agent with the trusted context.

        Single funnel: every path from the service to an agent carries a
        `Context`, so there is no way to reach a tool without one.
        """
        agent = self.route(user_message, context)
        return agent.run(messages, context)
