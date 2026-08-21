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
from app.ai.tools.insights._shared import day_bounds, fetch_entries

if TYPE_CHECKING:
    from supabase import AsyncClient

#: category -> keywords, matched case-insensitively as a substring of
#: "description reference". Order matters only in that the FIRST category
#: whose keywords match wins - keep more specific categories earlier if two
#: lists could ever overlap on the same merchant.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Abonamente / Streaming": ("spotify", "netflix", "hbo", "disney"),
    "Cumpărături alimentare": ("mega image", "carrefour", "lidl", "kaufland", "penny"),
    "Transport / Combustibil": ("omv", "petrom", "mol", "rompetrol"),
    "Electronice": ("emag", "e-mag", "altex", "pcgarage"),
    "Mâncare & Băutură": ("starbucks", "mcdonald", "kfc", "restaurant", "cafea"),
    "Telecomunicații": ("vodafone", "orange", "digi"),
    "Transferuri": ("revolut", "transfer"),
}
UNCATEGORIZED = "Altele"


def _categorize(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return UNCATEGORIZED


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

        date_from, date_to = day_bounds(validated_input.start_date, validated_input.end_date)
        entries = await fetch_entries(
            self._supabase,
            context,
            date_from=date_from,
            date_to=date_to,
            account_id=validated_input.account_id,
        )
        spending = [entry for entry in entries if entry.direction.value == "debit"]

        buckets: dict[str, dict[str, int]] = {}
        for entry in spending:
            category = _categorize(f"{entry.description} {entry.reference}")
            bucket = buckets.setdefault(category, {"count": 0, "total_minor": 0})
            bucket["count"] += 1
            bucket["total_minor"] += entry.amount_minor

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

        return ToolResult(
            name=self.name,
            data={
                "start_date": validated_input.start_date.isoformat(),
                "end_date": validated_input.end_date.isoformat(),
                "total_transactions": len(spending),
                "categories": categories,
                "uncategorized_count": buckets.get(UNCATEGORIZED, {}).get("count", 0),
            },
        )
