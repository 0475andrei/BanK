"""Rule-based spending categories from merchant name / description patterns.

Deliberately NOT ML: a fixed keyword map is deterministic, explainable, and
trivial to extend - matching a new merchant is a `dict` edit, not a retrain.
Everything a keyword doesn't catch falls into "Altele" ("Other"), which is
itself returned as an ordinary bucket in `categories` so its share of
spending is visible next to every named one, not hidden in a side field.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, model_validator

from app.ai.context import Context
from app.ai.schemas import ToolResult
from app.ai.tools.base import Tool
from app.ai.tools.insights._shared import day_bounds, load_rows

if TYPE_CHECKING:
    from supabase import AsyncClient

#: category -> keywords, matched case-insensitively as a substring of
#: "description reference". Order matters only in that the FIRST category
#: whose keywords match wins - keep more specific categories earlier if two
#: lists could ever overlap on the same merchant (e.g. "bolt food" must be
#: checked before plain "bolt", so a food-delivery order doesn't land in
#: Transport just because "bolt" is a substring of "bolt food").
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Facturi & Utilități": (
        "enel", "eon", "e.on", "electrica", "engie", "distrigaz", "apa nova",
        "hidroelectrica", "restart energy", "premier energy",
    ),
    "Telecomunicații": ("vodafone", "orange", "digi", "upc", "telekom"),
    "Divertisment": (
        "spotify", "netflix", "hbo", "disney", "cinema", "eventim",
        "bilete", "teatru", "twitch", "steam",
    ),
    "Mâncare & Băutură": (
        "starbucks", "mcdonald", "kfc", "restaurant", "cafea", "glovo",
        "tazz", "foodpanda", "bolt food",
    ),
    "Cumpărături alimentare": (
        "mega image", "carrefour", "lidl", "kaufland", "penny", "profi", "auchan",
    ),
    "Transport / Combustibil": (
        "omv", "petrom", "mol", "rompetrol", "uber", "bolt", "taxi", "cfr", "ratb", "stb",
    ),
    "Sănătate": (
        "catena", "sensiblu", "dona", "farmacie", "clinica", "spital", "reginamaria", "medlife",
    ),
    "Electronice": ("emag", "e-mag", "altex", "pcgarage", "media galaxy"),
    "Îmbrăcăminte": ("zara", "h&m", "bershka", "pull&bear", "decathlon"),
    "Educație": ("udemy", "coursera", "scoala", "școala", "universitate"),
    "Locuință & Amenajări": ("chirie", "ikea", "dedeman", "leroy merlin", "hornbach"),
    "Asigurări": ("allianz", "groupama", "generali", "nn asigurari"),
    "Transferuri": ("revolut", "transfer"),
}
UNCATEGORIZED = "Altele"


def _categorize(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return UNCATEGORIZED


async def categorize_spending(
    supabase: AsyncClient,
    context: Context,
    *,
    start_date: date,
    end_date: date,
    account_id: str | None = None,
) -> dict[str, Any]:
    """The actual work, shared by the chat tool below and the
    /insights/spending-by-category REST endpoint (see
    app/modules/insights/router.py) - the dashboard widget needs this
    synchronously, without going through an LLM tool-call loop just to
    render a chart on page load."""
    date_from, date_to = day_bounds(start_date, end_date)
    entries = await load_rows(
        supabase, context, date_from=date_from, date_to=date_to, account_id=account_id
    )
    spending = [entry for entry in entries if entry.direction.value == "debit"]

    buckets: dict[str, dict[str, int]] = {}
    row_categories: dict[str, str] = {}
    for entry in spending:
        category = _categorize(f"{entry.description} {entry.reference}")
        row_categories[str(entry.id)] = category
        bucket = buckets.setdefault(category, {"count": 0, "total_minor": 0})
        bucket["count"] += 1
        bucket["total_minor"] += entry.amount_minor

    if context.statement_id is not None:
        # Persist onto the extracted rows - NEVER onto the ledger, see
        # statements/service.py's module docstring. Sequential writes:
        # PostgREST has no per-row bulk-update-by-value primitive, and a
        # statement's row count is small enough (a few hundred at most)
        # that this isn't worth a bespoke batching path.
        from app.modules.statements import service as statements_service

        for row_id, category in row_categories.items():
            await statements_service.set_row_category(
                supabase, context.user_id, context.statement_id, row_id, category
            )

    total_minor = sum(bucket["total_minor"] for bucket in buckets.values())
    categories: list[dict[str, Any]] = [
        {
            "name": name,
            "count": bucket["count"],
            "total_minor": bucket["total_minor"],
            "percentage": (
                round(bucket["total_minor"] / total_minor * 100, 2) if total_minor else 0.0
            ),
        }
        for name, bucket in buckets.items()
    ]
    categories.sort(key=lambda c: int(c["total_minor"]), reverse=True)

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_transactions": len(spending),
        "categories": categories,
        "uncategorized_count": buckets.get(UNCATEGORIZED, {}).get("count", 0),
    }


class CategorizeTransactionsInput(BaseModel):
    """Arguments the model may supply. Validated, but still untrusted."""

    start_date: date = Field(
        description="First day to include, inclusive. ISO format, e.g. 2026-08-01."
    )
    end_date: date = Field(
        description="Last day to include, inclusive. ISO format, e.g. 2026-08-31."
    )
    account_id: str | None = Field(
        default=None,
        description=(
            "Optional. Restrict to one of the user's own accounts. Omit it to "
            "categorize spending across all of their accounts."
        ),
    )

    @model_validator(mode="after")
    def _range_is_ordered(self) -> CategorizeTransactionsInput:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class CategorizeTransactionsTool(Tool):
    name = "categorize_transactions"
    description = (
        "Break the user's spending (debit transactions only) down into "
        "categories - groceries, subscriptions, transport, etc. - based on "
        "merchant name patterns. Use this for 'what did I spend on X' or "
        "'spending by category' questions. Percentages are of total spending "
        "in the range, not of all transactions."
    )
    input_schema = CategorizeTransactionsInput
    read_only = True

    def __init__(self, supabase: AsyncClient) -> None:
        """`supabase` is the shared process-wide client (see db/supabase_client)."""
        self._supabase = supabase

    async def run(self, validated_input: BaseModel, context: Context) -> ToolResult:
        assert isinstance(validated_input, CategorizeTransactionsInput)

        data = await categorize_spending(
            self._supabase,
            context,
            start_date=validated_input.start_date,
            end_date=validated_input.end_date,
            account_id=validated_input.account_id,
        )
        return ToolResult(name=self.name, data=data)
