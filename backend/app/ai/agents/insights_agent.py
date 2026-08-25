"""The insights agent: analytical and observational, where banking is factual.

This is a genuinely different *kind* of reasoning, not just a different set of
tools — which is what makes it a separate agent rather than another tool group
on BankingAgent. BankingAgent answers "what is true right now" and is forbidden
from speculating; InsightsAgent is asked "what does this mean" and is expected
to interpret, compare periods, and point out patterns. One prompt cannot be
both strictly literal and usefully interpretive.

Still read-only: it may suggest what the user *could* do, never claim to have
done it. Write/propose tools arrive in Step 11.
"""

from __future__ import annotations

import logging

from app.ai.agents.tool_loop import ToolLoopAgent
from app.ai.routing import RoutingRule

logger = logging.getLogger(__name__)

#: Keyword STEMS matched as word prefixes on a diacritic-folded message (see
#: `RoutingRule.matched`). Split into several named rules so a persisted
#: `RoutingDecision.matched_rule` says WHICH kind of analytical intent fired,
#: not just "insights".
#:
#: OVERLAP WITH BANKING: `cheltui` and `bani` are also BankingAgent keywords
#: (added in Step 6, before this agent existed). "Cât am cheltuit?" therefore
#: matches both agents. That is resolved by registration order — AIService
#: registers this agent FIRST so the more specific analytical intent wins, per
#: the rule that Insights takes ambiguous analytical phrasing. See
#: `AIService.__init__`.
#:
#: `anul` rather than `an`: prefix matching means `an` would claim every word
#: starting with those two letters — including names like "Andrei", which would
#: send "trimite 50 RON către Andrei" to the analytics agent. `anul`/`anual`
#: cover "anul acesta" / "anul trecut" without that blast radius.
#:
#: `"anul "` (trailing space) rather than bare `"anul"`: prefix matching also
#: means `anul` claims "anulează"/"anulare"/"anulat" (cancel-family words,
#: e.g. propose_cancel_card's "anulează cardul meu" - see
#: app/ai/tools/propose_tools.py), sending a card-cancellation request here
#: instead of to Banking. The trailing space still matches "anul acesta" /
#: "anul trecut" (a space always follows in that phrasing) while rejecting
#: "anulează", which continues the same word with no boundary. Narrow
#: regression: no longer matches "anul" as the very last word of a message,
#: or followed by punctuation instead of a space - accepted, since the
#: false-positive it fixes actively broke a real feature.
INSIGHTS_ROUTING_RULES = (
    RoutingRule(
        name="insights_spending",
        keywords=frozenset({"cheltui", "spend", "expense"}),
    ),
    RoutingRule(
        name="insights_analysis",
        keywords=frozenset({"analiz", "tendin", "trend", "patter", "unde"}),
    ),
    RoutingRule(
        name="insights_categories",
        keywords=frozenset(
            {"categori", "abonament", "subscription", "recurent", "recurring"}
        ),
    ),
    RoutingRule(
        name="insights_time_slice",
        keywords=frozenset(
            {
                "saptaman",
                "week",
                "luna",
                "lunar",
                "month",
                "trimestr",
                "quarter",
                "anul ",
                "anual",
            }
        ),
    ),
)

SYSTEM_PROMPT = """Ești asistentul analitic al băncii. Rolul tău este să ajuți
utilizatorul să înțeleagă cum își cheltuie și își gestionează banii — analize,
categorii, tendințe, tipare de cheltuieli.

REGULI:
- Ai voie să interpretezi datele și să oferi observații („pare că cheltuielile
  tale pe mâncare s-au dublat comparativ cu luna trecută").
- NU inventa cifre — folosește doar datele returnate de instrumente.
- NU poți efectua acțiuni: nu poți muta bani, seta limite, bloca carduri, sau
  modifica conturi. Dacă utilizatorul cere așa ceva, spune clar că poți doar să
  analizezi, nu să acționezi.
- Poți sugera ce ar putea utilizatorul să facă („ai putea să-ți setezi o limită
  pe categoria X"), dar niciodată să nu pretinzi că ai făcut-o.
- Convertește sumele din unități minore în format lizibil (RON cu virgulă
  zecimală, două zecimale: 50000 înseamnă „500,00 RON").
- Datele: pentru interogări cu intervale („săptămâna trecută", „luna
  octombrie", „ultimele 3 luni"), calculează tu datele ISO (start_date,
  end_date) și pasează-le instrumentului. Data de azi este ziua curentă.
- `direction` este „debit" (bani ieșiți) sau „credit" (bani intrați).
  Cheltuielile sunt tranzacțiile de tip debit.
- Dacă instrumentul întoarce o listă goală, spune clar că nu există activitate
  în intervalul cerut — nu este o eroare.
- Formatează răspunsurile în română, concis dar cu observații utile — nu doar
  tabele.

INSTRUMENTE DISPONIBILE:
- get_transactions_in_range: preia tranzacțiile utilizatorului dintr-un interval
  de date, pe toate conturile. Folosește pentru analize, categorii, tendințe.
- categorize_transactions: împarte cheltuielile într-un interval pe categorii
  (mâncare, abonamente, transport etc.). Folosește pentru „ce am cheltuit pe
  mâncare?" sau „categorii de cheltuieli".
- detect_recurring_payments: găsește plățile recurente / abonamentele din
  istoricul tranzacțiilor. Folosește pentru „am abonamente recurente?", „ce
  abonamente am?" sau „cât plătesc pe subscripții?".
- compute_spending_stats: calculează statistici agregate (venituri, cheltuieli,
  net, medii, cea mai mare/mică tranzacție, ziua cu cele mai multe cheltuieli)
  pentru un interval. Folosește pentru „cât am cheltuit luna asta?",
  „statistici" sau „rezumat financiar".
- detect_anomalies: semnalează tranzacții neobișnuite (sumă mult peste normal
  sau comerciant niciodată văzut până acum). Folosește pentru „am cheltuieli
  neobișnuite?", „ceva suspect?" sau „tranzacții ciudate".

Poți combina instrumente în aceeași conversație când întrebarea o cere - de
exemplu „rezumatul lunii" poate însemna atât compute_spending_stats cât și
categorize_transactions.
"""

FALLBACK_REPLY = (
    "Nu am reușit să duc analiza la capăt — am tot avut nevoie de date "
    "suplimentare și m-am oprit ca să nu intru în buclă. Încearcă să "
    "reformulezi întrebarea."
)


class InsightsAgent(ToolLoopAgent):
    """Analytical agent over the user's transaction history."""

    name = "insights"
    routing_rules = INSIGHTS_ROUTING_RULES
    system_prompt = SYSTEM_PROMPT
    fallback_reply = FALLBACK_REPLY
