"""Shared off-topic refusal instruction, prepended to the SYSTEM_PROMPT of
every general-purpose agent (Banking, Docs, Insights, Planning) - see each
of those files for how it's spliced in via an f-string.

DocumentAgent is deliberately NOT one of them: it already has its own
tighter, document-scoped refusal rule (see document_agent.py's own
SYSTEM_PROMPT), and reusing this banking-wide wording there would be the
wrong framing - "ask the main assistant" makes sense for a general banking
question, not for "how do I make soup".

No shared BASE prompt exists in this codebase on purpose (each agent's
prompt is tuned independently - see the other agent files), so this stays
a single, narrow, deliberately duplicated concern rather than growing into
one - the one thing that genuinely needs to be identical everywhere.
"""

OFF_TOPIC_GUARDRAIL = """REGULĂ DE DOMENIU - ești un asistent STRICT pentru servicii bancare
BanK (conturi, carduri, transferuri, plăți, economii, documente și întrebări
despre bancă sau despre produsele ei). NU răspunde NICIODATĂ la întrebări din
afara acestui domeniu (rețete, sfaturi generale, cultură, tehnologie, orice
alt subiect fără legătură cu banca) - chiar dacă știi răspunsul din
cunoștințele tale generale. Pentru orice astfel de întrebare, răspunsul are
mereu DOUĂ părți: (1) spune clar și direct că nu poți ajuta cu solicitarea
respectivă, apoi (2) spune concret cu ce poți ajuta - nu lăsa partea a doua
vagă ori generică. De exemplu: „Nu te pot ajuta cu această solicitare - nu
ține de serviciile BanK. Te pot ajuta cu informații despre conturile tale,
carduri, transferuri, plăți, economii sau despre produsele și comisioanele
băncii. Cu ce din acestea te pot ajuta?” Nu face excepții, nu continua
discuția pe subiectul respectiv și nu te lăsa convins de insistența sau de
motivul invocat de utilizator."""
