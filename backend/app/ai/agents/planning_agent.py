"""The planning agent: goal-oriented and forward-looking, where Banking is
factual ("what IS") and Insights is retrospective ("what WAS/DID").

Planning is asked "what happens next, and can I get where I want to be" - a
third kind of reasoning again, not a third tool group bolted onto an
existing agent. Still read-only: it proposes and projects, it never acts.
Propose/confirm (write tools with user approval) arrive in Step 11.
"""

from __future__ import annotations

import logging

from app.ai.agents.scope_guardrail import OFF_TOPIC_GUARDRAIL
from app.ai.agents.tool_loop import ToolLoopAgent
from app.ai.routing import RoutingRule

logger = logging.getLogger(__name__)

#: Keyword STEMS matched as word prefixes on a diacritic-folded message (see
#: `RoutingRule.matched`). Split into several named rules so a persisted
#: `RoutingDecision.matched_rule` says WHICH kind of planning intent fired.
#:
#: KNOWN COLLISION: `econom` is also a BankingAgent keyword (its "Economii"
#: account). "Vreau să economisesc 500 lei" therefore matches both agents,
#: and BankingAgent wins - it is registered first (and is the default), and
#: `Orchestrator._match_rules` stops at the first agent whose rule claims the
#: message. That means a savings-goal phrasing built only around "economii"
#: currently routes to Banking, not Planning. Acceptable for now: it costs a
#: mis-route on a fairly narrow phrasing, not a broken feature (the other
#: planning stems below still catch most real goal/projection/scenario
#: questions), and re-splitting the keyword sets needs a real look at
#: BankingAgent's rules too - out of scope here. Revisit in Step 16.
PLANNING_ROUTING_RULES = (
    RoutingRule(
        name="planning_goals",
        keywords=frozenset({"obiectiv", "goal", "econom", "sav", "strangi", "adun"}),
    ),
    RoutingRule(
        name="planning_projection",
        keywords=frozenset({"proiect", "proiecti", "predict", "forecast", "viitor", "futur"}),
    ),
    RoutingRule(
        name="planning_scenario",
        keywords=frozenset({"daca", "what if", "simul", "scenari", "presupun"}),
    ),
    RoutingRule(
        name="planning_timeline",
        keywords=frozenset({"cand", "when", "pana", "by when", "termen"}),
    ),
    RoutingRule(
        name="planning_budget",
        keywords=frozenset({"buget", "budget", "plan", "strategi"}),
    ),
)

SYSTEM_PROMPT = f"""{OFF_TOPIC_GUARDRAIL}

Ești planificatorul financiar al băncii. Rolul tău este să
ajuți utilizatorul să planifice, să proiecteze și să simuleze scenarii
financiare viitoare.

REGULI:
- Gândește orientat pe obiective: utilizatorul are un scop („vreau să-mi iau
  un PS5", „vreau să economisesc pentru vacanță") — ajută-l să ajungă acolo.
- Folosește datele reale ale utilizatorului (sold curent, venituri/cheltuieli
  recente) pentru proiecții realiste.
- Poți sugera acțiuni concrete („ar trebui să economisești 285 RON pe lună"),
  dar NU poți executa nimic — nu muti bani, nu creezi transferuri, nu setezi
  automatizări.
- Dacă un obiectiv nu este realizabil în termenul dat, spune-o direct și
  oferă alternative (termen mai lung, sumă mai mică, reducere cheltuieli).
- Convertește sumele din unități minore în format lizibil (RON cu virgulă
  zecimală, două zecimale: 50000 înseamnă „500,00 RON").
- Toate datele și răspunsurile în română.

INSTRUMENTE DISPONIBILE:
- project_balance: proiectează soldul pe N luni, bazat pe istoricul real sau
  pe un ritm de economisire specificat.
- simulate_scenario: „ce-ar fi dacă?" — aplică ajustări (reducere cheltuieli,
  mărire venituri) și compară cu scenariul de bază.
- savings_goal: verifică dacă un obiectiv financiar este realizabil într-un
  termen dat și cât trebuie economisit lunar.
"""

FALLBACK_REPLY = (
    "Nu am reușit să duc planificarea la capăt — am tot avut nevoie de date "
    "suplimentare și m-am oprit ca să nu intru în buclă. Încearcă să "
    "reformulezi întrebarea."
)


class PlanningAgent(ToolLoopAgent):
    """Goal-oriented agent that projects and simulates the user's finances."""

    name = "planning"
    routing_rules = PLANNING_ROUTING_RULES
    system_prompt = SYSTEM_PROMPT
    fallback_reply = FALLBACK_REPLY
