"""Routes an incoming message to the agent that should handle it.

A rule-hybrid classifier, in strict precedence order:

1. **Rules.** Each agent declares keyword stems it claims (`Agent.routing_rules`).
   First rule that matches wins, at full confidence. Deterministic, free, and
   testable without a model.
2. **Single agent.** With only one agent registered there is nothing to decide,
   so an unmatched message goes there rather than burning a model call on a
   foregone conclusion. This is today's common path.
3. **LLM fallback.** Several agents, no rule matched: ask the model to classify.
   Its answer is untrusted — anything not a registered agent name is discarded
   in favour of the default.

Every path returns a `RoutingDecision`, never a bare agent, so the choice can be
persisted and shown to a user instead of being invisible.

Adding an agent is `register()` plus rules on the agent class. Nothing in this
file changes.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.ai.agents.base import Agent
from app.ai.context import Context
from app.ai.routing import RoutingDecision, normalise
from app.ai.schemas import Message

if TYPE_CHECKING:
    from app.ai.providers.base import ModelProvider

logger = logging.getLogger(__name__)

#: Confidence attached to an LLM-classified route. Deliberately a constant
#: rather than a number parsed out of the model's reply: asking a model to
#: self-report calibrated confidence produces fluent noise, and a fixed value at
#: least means the same thing every time.
LLM_FALLBACK_CONFIDENCE = 0.7


class Orchestrator:
    """Holds the registered agents and picks one per message."""

    def __init__(
        self,
        agents: list[Agent] | None = None,
        *,
        default: str | None = None,
        provider: ModelProvider | None = None,
    ) -> None:
        self._agents: dict[str, Agent] = {}
        # `register` consults `_default`, so it must exist first.
        self._default: str | None = None
        # Only used for the LLM fallback. Optional: with one agent (or with
        # rules covering everything) routing never needs a model at all.
        self._provider = provider
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

    def route(self, message: str, context: Context) -> RoutingDecision:
        """Pick the agent for this message and say why.

        `context` is accepted so identity-aware routing (product tier,
        entitlements) can be added without changing this signature again; it is
        not consulted yet.
        """
        del context  # not consulted yet
        if self._default is None:
            raise RuntimeError("Orchestrator has no agents registered")

        rule_decision = self._match_rules(message)
        if rule_decision is not None:
            return rule_decision

        if len(self._agents) == 1:
            return RoutingDecision(
                agent_name=self._default,
                reason="Only one agent registered",
                confidence=1.0,
            )

        return self._classify_with_model(message)

    def _match_rules(self, message: str) -> RoutingDecision | None:
        """First rule that claims the message wins. None if nothing matched."""
        normalised = normalise(message)

        for agent_name, agent in self._agents.items():
            for rule in agent.routing_rules:
                matched = rule.matched(normalised)
                if not matched:
                    continue
                # Sorted so the same match always reads the same way in an
                # audit trail. Only keywords appear here - never the message.
                keywords = ", ".join(f"'{kw}'" for kw in sorted(matched))
                return RoutingDecision(
                    agent_name=agent_name,
                    reason=f"Matched rule: keywords {keywords}",
                    confidence=1.0,
                    matched_rule=rule.name,
                )
        return None

    def _classify_with_model(self, message: str) -> RoutingDecision:
        """Ask the model which agent should answer. Never raises.

        The model's answer is untrusted input like any other: it is only
        accepted when it names an agent that is actually registered. Anything
        else - a hallucinated name, prose, an empty reply, a provider outage -
        degrades to the default agent, because refusing to answer the user at
        all would be a worse failure than answering from the wrong agent.
        """
        assert self._default is not None  # guarded by route()

        if self._provider is None:
            logger.warning("no provider for LLM routing fallback; using default agent")
            return RoutingDecision(
                agent_name=self._default,
                reason="No classifier provider available; used default agent",
                confidence=LLM_FALLBACK_CONFIDENCE,
            )

        prompt = (
            "You are a routing classifier. Given a user message, respond with "
            f"ONLY the agent name (one of: {', '.join(self.names())}). "
            "No punctuation, no explanation. If the message is ambiguous, "
            f"respond with the default agent name: {self._default}."
        )

        try:
            response = self._provider.complete(
                [
                    Message(role="system", content=prompt),
                    Message(role="user", content=message),
                ]
            )
        except Exception:
            # Includes ProviderError. Routing must not be able to take down a
            # request that the default agent could have answered.
            logger.warning("LLM routing failed; using default agent", exc_info=True)
            return RoutingDecision(
                agent_name=self._default,
                reason="Classifier unavailable; used default agent",
                confidence=LLM_FALLBACK_CONFIDENCE,
            )

        candidate = (response.text or "").strip()
        if candidate in self._agents:
            return RoutingDecision(
                agent_name=candidate,
                reason="Classified by model",
                confidence=LLM_FALLBACK_CONFIDENCE,
            )

        # Never log the candidate itself - it is model-authored text that may
        # contain anything, including whatever the user just typed.
        logger.warning(
            "LLM routing returned an unregistered agent name; using default agent"
        )
        return RoutingDecision(
            agent_name=self._default,
            reason="Classifier returned an unknown agent; used default agent",
            confidence=LLM_FALLBACK_CONFIDENCE,
        )

    async def dispatch(
        self,
        messages: Sequence[Message],
        user_message: str,
        context: Context,
    ) -> tuple[str, list[Message], RoutingDecision]:
        """Route, then run the chosen agent with the trusted context.

        Single funnel: every path from the service to an agent carries a
        `Context`, so there is no way to reach a tool without one. Returns
        `(reply, trace, routing)` - the trace exactly as `Agent.run` produced
        it, plus the decision that picked the agent, so callers can persist and
        surface it.

        TODO: if this grows past 3 elements, switch to a TurnResult Pydantic
        model rather than widening the tuple again.
        """
        decision = self.route(user_message, context)
        agent = self._agents[decision.agent_name]
        reply, trace = await agent.run(messages, context)
        return reply, trace, decision
