"""The banking agent: provider + system prompt + its own tool subset."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.ai.agents.base import Agent
from app.ai.context import Context
from app.ai.providers.base import ModelProvider
from app.ai.schemas import Message, ToolCall, ToolResult
from app.ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the banking assistant for a personal banking app.

You may READ the user's data using the tools provided. You cannot move money,
open or close accounts, or change anything — no such tool exists, and you must
never claim to have performed an action.

Rules:
- Use a tool when you need real account data; never invent numbers.
- You do not know who the user is and you do not need to. The application
  supplies their identity to the tools. Never guess, invent, or ask the user for
  an account identifier — call the tool without one and it will use their
  default account.
- Balances come back as an integer in MINOR units (e.g. cents) plus a currency
  code. Convert to a human-readable amount when you answer (12345 USD minor
  units is $123.45).
- If a tool reports an error, say plainly what you could not do.
- Be brief and factual.
"""

#: Cap on provider round-trips per user message. Prevents an infinite tool loop.
MAX_ITERATIONS = 5

FALLBACK_REPLY = (
    "I wasn't able to finish that request — I kept needing more information and "
    "stopped to avoid looping. Please try rephrasing it."
)


class BankingAgent(Agent):
    """Runs the read-only tool loop against a provider."""

    name = "banking"

    def __init__(
        self,
        provider: ModelProvider,
        tools: ToolRegistry,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        max_iterations: int = MAX_ITERATIONS,
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        self._provider = provider
        self._tools = tools
        self._system_prompt = system_prompt
        self._max_iterations = max_iterations

    async def run(self, messages: Sequence[Message], context: Context) -> tuple[str, list[Message]]:
        # `context` is threaded straight to the tools and is never rendered into
        # the prompt — the model must not be able to read or restate identity.
        #
        # Local working copy: the caller's history is never mutated. Everything
        # appended after the system prompt + caller's messages is the trace this
        # call hands back, so the caller can persist it.
        working: list[Message] = [
            Message(role="system", content=self._system_prompt),
            *messages,
        ]
        trace_start = len(working)
        specs = self._tools.list_specs()

        for iteration in range(1, self._max_iterations + 1):
            response = self._provider.complete(working, specs)

            if not response.wants_tools:
                return response.text or "", working[trace_start:]

            working.append(response.to_assistant_message())
            for call in response.tool_calls:
                # Log the tool name only — arguments and results may carry PII.
                logger.info(
                    "agent=%s iteration=%d executing tool=%s",
                    self.name,
                    iteration,
                    call.name,
                )
                result = await self._execute(call, context)
                working.append(result.to_message())

        logger.warning(
            "agent=%s hit max_iterations=%d; returning fallback",
            self.name,
            self._max_iterations,
        )
        return FALLBACK_REPLY, working[trace_start:]

    async def _execute(self, call: ToolCall, context: Context) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            # The model asked for something it was never offered.
            logger.warning("agent=%s requested unknown tool=%s", self.name, call.name)
            return ToolResult.failure(
                name=call.name,
                error=f"unknown tool: {call.name}",
                tool_call_id=call.id,
            )
        # `execute` validates arguments, enforces the context, and never raises.
        return await tool.execute(call, context)
