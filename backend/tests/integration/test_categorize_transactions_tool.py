"""`categorize_transactions` against the real Supabase-backed ledger."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.ai.context import build_context_for_user
from app.ai.schemas import ToolCall
from app.ai.tools.insights import CategorizeTransactionsTool


def _call(call_id: str = "c1", **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name="categorize_transactions", arguments=arguments)


def _iso(days_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).date().isoformat()


async def _seed_entry(
    supabase,
    account_id,
    amount_minor: int,
    *,
    days_ago: int = 0,
    direction: str = "debit",
    description: str = "Test entry",
    currency: str = "RON",
) -> None:
    journal = (
        await supabase.table("journal_transactions")
        .insert(
            {
                "reference": "TEST-CATEGORIZE",
                "idempotency_key": f"test-categorize-{uuid.uuid4()}",
                "description": description,
            }
        )
        .execute()
    ).data[0]
    await supabase.table("ledger_entries").insert(
        {
            "journal_id": journal["id"],
            "account_id": str(account_id),
            "direction": direction,
            "amount_minor": amount_minor,
            "currency": currency,
            "created_at": (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
        }
    ).execute()


async def test_categorize_assigns_correct_categories(supabase, user_factory, account_factory):
    user = await user_factory()
    account = await account_factory(user)
    await _seed_entry(supabase, account["id"], 3_000, description="Spotify Premium")
    await _seed_entry(supabase, account["id"], 15_000, description="Lidl Cluj")
    await _seed_entry(supabase, account["id"], 5_000, description="Random Thing Store")

    context = await build_context_for_user(user, supabase)
    result = await CategorizeTransactionsTool(supabase).execute(
        _call(start_date=_iso(5), end_date=_iso(0)), context
    )

    assert result.ok, result.error
    by_name = {c["name"]: c for c in result.data["categories"]}
    assert by_name["Divertisment"]["count"] == 1
    assert by_name["Divertisment"]["total_minor"] == 3_000
    assert by_name["Cumpărături alimentare"]["count"] == 1
    assert by_name["Cumpărături alimentare"]["total_minor"] == 15_000
    assert by_name["Altele"]["count"] == 1
    assert result.data["total_transactions"] == 3
    assert result.data["uncategorized_count"] == 1


async def test_categorize_percentages_sum_to_100(supabase, user_factory, account_factory):
    user = await user_factory()
    account = await account_factory(user)
    await _seed_entry(supabase, account["id"], 3_000, description="Spotify")
    await _seed_entry(supabase, account["id"], 7_000, description="Lidl")
    await _seed_entry(supabase, account["id"], 2_000, description="Mystery Store")

    context = await build_context_for_user(user, supabase)
    result = await CategorizeTransactionsTool(supabase).execute(
        _call(start_date=_iso(5), end_date=_iso(0)), context
    )

    assert result.ok, result.error
    total_percentage = sum(c["percentage"] for c in result.data["categories"])
    assert total_percentage == pytest.approx(100.0, abs=0.1)


async def test_categorize_handles_empty_range(supabase, user_factory, account_factory):
    user = await user_factory()
    await account_factory(user)

    context = await build_context_for_user(user, supabase)
    result = await CategorizeTransactionsTool(supabase).execute(
        _call(start_date=_iso(5), end_date=_iso(0)), context
    )

    assert result.ok, result.error
    assert result.data["categories"] == []
    assert result.data["total_transactions"] == 0
    assert result.data["uncategorized_count"] == 0


async def test_categorize_is_case_insensitive(supabase, user_factory, account_factory):
    user = await user_factory()
    account = await account_factory(user)
    await _seed_entry(supabase, account["id"], 1_000, description="SPOTIFY", days_ago=1)
    await _seed_entry(supabase, account["id"], 1_000, description="spotify premium", days_ago=0)

    context = await build_context_for_user(user, supabase)
    result = await CategorizeTransactionsTool(supabase).execute(
        _call(start_date=_iso(5), end_date=_iso(0)), context
    )

    assert result.ok, result.error
    by_name = {c["name"]: c for c in result.data["categories"]}
    assert by_name["Divertisment"]["count"] == 2
