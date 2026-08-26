"""What a routing decision *is* — the types, not the machinery.

Lives apart from `orchestrator.py` for a concrete reason, not taste:
`agents/base.py` declares `routing_rules` as a class attribute, so it must
import `RoutingRule`, and `orchestrator.py` already imports `agents/base.py`.
Putting these types in `orchestrator.py` would close that loop into a circular
import. Keeping them here also separates "what a decision is" from "how routing
is executed", which is what makes the decision safe to persist and return over
HTTP without dragging the orchestrator along.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field


def normalise(message: str) -> str:
    """Fold a message down to something keyword matching can rely on.

    Strips diacritics and lowercases, so `tranzacție`, `Tranzactie` and
    `TRANZACȚIE` are all the same string by the time a rule sees them. Romanian
    is routinely typed without diacritics, and a router that only matched the
    correctly-accented spelling would miss most real messages.
    """
    decomposed = unicodedata.normalize("NFKD", message)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_marks.lower()


class RoutingRule(BaseModel):
    """A named set of keyword stems that claim a message for an agent."""

    model_config = ConfigDict(frozen=True)

    name: str
    keywords: frozenset[str]

    def matched(self, normalised_message: str) -> frozenset[str]:
        """Which of this rule's keywords appear in the message. Empty = no match.

        Keywords are matched as word PREFIXES (`\\bsold` catches sold, soldul,
        soldurile) because Romanian inflects heavily — exact word matching would
        miss `cardurile mele` while matching `card`.

        KNOWN LIMITATION: prefix matching over-matches. `cont` also fires on
        `contact`, `plat` on `platformă`. That is harmless while BankingAgent is
        the only agent registered — every message routes there regardless — but
        it must be revisited when InsightsAgent registers and a mis-route starts
        costing something. Tighten the stems (or add negative keywords) then,
        rather than guessing at the shape of the problem now.
        """
        return frozenset(
            keyword
            for keyword in self.keywords
            if re.search(rf"\b{re.escape(keyword)}", normalised_message)
        )


class RoutingDecision(BaseModel):
    """Which agent handled a message, and why.

    Frozen: a decision is a record of something that already happened, so
    nothing downstream — persistence, the HTTP response, a future UI — may
    quietly rewrite it.

    `reason` is written for a human reading an audit trail. It names the rule
    and the keywords that fired, never the user's message: the transcript
    already holds what they said, and a reason that echoed it would duplicate
    user content into a field nobody expects to be sensitive.
    """

    model_config = ConfigDict(frozen=True)

    agent_name: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    matched_rule: str | None = None
    #: Set only on a hop that a PREVIOUS agent handed the turn to (Step 15):
    #: the name of the agent it came from. None means this decision came from
    #: `Orchestrator.route()` - i.e. it is the first hop of a turn, or the
    #: whole turn.
    #:
    #: No migration needed for this field. `messages.routing_metadata` is
    #: JSONB, so an extra key just stores; and because it defaults to None,
    #: every row written before Step 15 reads back as `handoff_from=None`,
    #: which is exactly what those turns were.
    handoff_from: str | None = None
