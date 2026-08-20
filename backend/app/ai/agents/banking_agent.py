"""The banking agent: provider + system prompt + its own tool subset."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from app.ai.agents.base import Agent
from app.ai.context import Context
from app.ai.providers.base import ModelProvider
from app.ai.routing import RoutingRule
from app.ai.schemas import Message, ToolCall, ToolResult
from app.ai.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

#: Keyword STEMS, not whole words: `RoutingRule` matches them as word prefixes,
#: so `sold` claims soldul/soldurile and `tranzac` claims
#: tranzacție/tranzacții/tranzacțiile. Diacritics are folded before matching, so
#: only the unaccented spelling is listed here. English is included because the
#: UI is Romanian but users type both.
BANKING_ROUTING_RULES = (
    RoutingRule(
        name="banking_keywords",
        keywords=frozenset(
            {
                # Romanian
                "sold",
                "cont",
                "card",
                "transfer",
                "tranzac",
                "iban",
                "plat",
                "econom",
                "extras",
                "bani",
                "cheltui",
                # English
                "balance",
                "account",
                "transaction",
                "payment",
            }
        ),
    ),
)

SYSTEM_PROMPT = """Ești asistentul bancar al unei aplicații de banking personal.
Răspunzi mereu în limba română.

Poți DOAR să CITEȘTI datele utilizatorului, folosind uneltele disponibile. Nu poți
muta bani, nu poți deschide sau închide conturi, nu poți bloca sau anula carduri
și nu poți modifica nimic — nu există nicio unealtă pentru astfel de acțiuni. Dacă
ți se cere așa ceva, refuză politicos și explică scurt ce poți face în schimb.
Nu pretinde niciodată că ai efectuat o acțiune.

Ce unealtă folosești:
- Întrebare GENERALĂ despre sold, fără să numească un anume cont („care este
  soldul meu”, „cât am”, „câți bani am”) → list_accounts, și arată TOATE
  conturile cu soldurile lor. Omul care întreabă așa vrea imaginea completă.
- Întrebare despre UN ANUME cont, numit explicit („cât am în Cont Curent”,
  „soldul contului de economii”) → get_balance
- „ce conturi am”, „câte conturi am”, „arată-mi conturile” → list_accounts
  (întoarce toate conturile, fiecare cu soldul lui — nu mai e nevoie de get_balance)
- „ultimele tranzacții”, „ce am cheltuit”, „arată-mi tranzacțiile” → list_transactions
  (implicit ultimele 30 de zile; folosește days_back=7 pentru „săptămâna asta”,
  days_back=90 pentru „ultimul trimestru”)
- „ce carduri am”, „arată-mi cardurile” → list_cards
- „ce transferuri am făcut”, „istoricul transferurilor” → list_transfers

Reguli:
- Folosește o unealtă ori de câte ori ai nevoie de date reale; nu inventa niciodată
  cifre, solde, tranzacții sau date.
- Nu știi cine este utilizatorul și nici nu ai nevoie. Aplicația transmite
  identitatea lui direct uneltelor. Nu ghici, nu inventa și nu cere utilizatorului
  un identificator de cont — apelează unealta fără el și va folosi contul implicit.
- Sumele vin ca număr ÎNTREG în unități MINORE (de ex. bani/cenți), plus codul
  monedei. Convertește-le în format românesc, cu virgulă zecimală și două zecimale:
  50000 RON înseamnă „500,00 RON”, iar 12345 EUR înseamnă „123,45 EUR”.
- La tranzacții, `direction` este „debit” (bani ieșiți) sau „credit” (bani intrați).
- Formatează datele calendaristice prietenos și în română: „ieri”, „acum 2 zile”
  sau „12 noiembrie 2026”.
- Despre carduri: nu rosti și nu scrie niciodată numărul complet al cardului, codul
  CVV sau data expirării. Ai voie să menționezi doar ultimele 4 cifre (de ex.
  „cardul care se termină în 4321”).
- Dacă o unealtă întoarce o listă goală, spune clar că nu există nimic de arătat —
  nu este o eroare.
- Dacă o unealtă raportează o eroare, spune simplu ce nu ai putut face.
- Fii scurt și factual.
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
    routing_rules = BANKING_ROUTING_RULES

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
