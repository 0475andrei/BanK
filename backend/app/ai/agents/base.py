"""The agent contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.ai.context import Context
from app.ai.schemas import Message


class Agent(ABC):
    """Turns a conversation into one final assistant reply."""

    #: Stable identifier the orchestrator routes to.
    name: str

    @abstractmethod
    async def run(self, messages: Sequence[Message], context: Context) -> str:
        """Produce the final reply text. Must not mutate `messages`.

        `context` is the trusted identity the agent acts for; it is passed to
        every tool and is never derived from the conversation.
        """
        raise NotImplementedError
