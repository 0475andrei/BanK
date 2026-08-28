"""`list_accounts` against real Supabase-backed accounts and ledger.

The offline contract tests live in tests/ai/test_tools.py; these prove the
accounts the model is handed are genuinely the context user's, with balances
that are genuinely SUM(ledger_entries).
"""

from app.ai.context import build_context_for_user
from app.ai.schemas import ToolCall
from app.ai.tools.banking import GetBalanceTool, ListAccountsTool


def _call(call_id: str = "c1", *, include_closed: bool = False) -> ToolCall:
    return ToolCall(
        id=call_id, name="list_accounts", arguments={"include_closed": include_closed}
    )


async def _close(supabase, account_id: str) -> None:
    await supabase.table("accounts").update({"status": "closed"}).eq("id", account_id).execute()


async def test_list_accounts_returns_all_user_accounts_with_balances(
    supabase, user_factory, account_factory, seed_balance_factory
):
    user = await user_factory()
    checking = await account_factory(user, name="Checking")
    savings = await account_factory(user, name="Savings")
    await seed_balance_factory(checking["id"], 12_300)
    await seed_balance_factory(savings["id"], 45_600)

    context = await build_context_for_user(user, supabase)
    result = await ListAccountsTool(supabase).execute(_call(), context)

    assert result.ok, result.error
    accounts = result.data["accounts"]
    assert len(accounts) == 2

    by_name = {account["name"]: account for account in accounts}
    assert by_name["Checking"]["balance_minor"] == 12_300
    assert by_name["Savings"]["balance_minor"] == 45_600
    assert by_name["Checking"]["id"] == str(checking["id"])
    assert by_name["Savings"]["id"] == str(savings["id"])
    # The full shape the model is handed.
    assert set(by_name["Checking"]) == {
        "id",
        "name",
        "currency",
        "iban",
        "status",
        "balance_minor",
    }
    assert by_name["Checking"]["currency"] == "USD"
    assert by_name["Checking"]["status"] == "active"


async def test_list_accounts_returns_empty_list_for_user_with_no_accounts(
    supabase, user_factory
):
    """A just-registered user has no accounts. That is a legitimate state and
    must read as an empty list, never as an error."""
    user = await user_factory()

    context = await build_context_for_user(user, supabase)
    result = await ListAccountsTool(supabase).execute(_call(), context)

    assert result.ok, result.error
    assert result.data["accounts"] == []


async def test_list_accounts_does_not_leak_other_users_accounts(
    supabase, user_factory, account_factory, seed_balance_factory
):
    """SECURITY: the account set comes from the context user's id, so another
    user's accounts are not reachable — the tool takes no arguments at all."""
    alice = await user_factory()
    bob = await user_factory()
    alice_account = await account_factory(alice, name="Alice Checking")
    bob_account = await account_factory(bob, name="Bob Checking")
    await seed_balance_factory(bob_account["id"], 999_999)

    alice_context = await build_context_for_user(alice, supabase)
    result = await ListAccountsTool(supabase).execute(_call(), alice_context)

    assert result.ok, result.error
    returned_ids = [account["id"] for account in result.data["accounts"]]
    assert returned_ids == [str(alice_account["id"])]
    assert str(bob_account["id"]) not in returned_ids


async def test_list_accounts_excludes_a_closed_account_by_default(
    supabase, user_factory, account_factory, seed_balance_factory
):
    """Bug: a user closes an account via chat, then in a later conversation
    asks for their balance and the closed account still showed up. The fix is
    a default status filter in accounts_service.list_accounts_for_owner - this
    proves it reaches the AI tool the model actually calls."""
    user = await user_factory()
    open_account = await account_factory(user, name="Checking")
    closed_account = await account_factory(user, name="Old Savings")
    await seed_balance_factory(open_account["id"], 10_000)
    await _close(supabase, closed_account["id"])

    # The Context itself is built after the close, so its own account
    # allowlist (used everywhere else - get_balance's default, propose_*,
    # planning) already excludes the closed account too.
    context = await build_context_for_user(user, supabase)
    assert str(closed_account["id"]) not in context.account_ids

    result = await ListAccountsTool(supabase).execute(_call(), context)

    assert result.ok, result.error
    returned_ids = [account["id"] for account in result.data["accounts"]]
    assert returned_ids == [str(open_account["id"])]
    assert str(closed_account["id"]) not in returned_ids


async def test_list_accounts_includes_closed_accounts_when_explicitly_requested(
    supabase, user_factory, account_factory, seed_balance_factory
):
    user = await user_factory()
    open_account = await account_factory(user, name="Checking")
    closed_account = await account_factory(user, name="Old Savings")
    await seed_balance_factory(open_account["id"], 10_000)
    await _close(supabase, closed_account["id"])

    # A closed account is not in account_ids, so it cannot be resolved as a
    # specific/default account by other tools - but list_accounts still needs
    # to be able to SHOW it, since context.account_ids is not consulted by the
    # underlying accounts_service query here.
    context = await build_context_for_user(user, supabase)
    result = await ListAccountsTool(supabase).execute(
        _call(include_closed=True), context
    )

    assert result.ok, result.error
    by_id = {account["id"]: account for account in result.data["accounts"]}
    assert set(by_id) == {str(open_account["id"]), str(closed_account["id"])}
    assert by_id[str(closed_account["id"])]["status"] == "closed"


async def test_get_balance_default_account_skips_a_closed_first_account(
    supabase, user_factory, account_factory, seed_balance_factory
):
    """A closed account must not become the implicit default just because it
    was opened first (account_ids[0])."""
    user = await user_factory()
    closed_account = await account_factory(user, name="Old Checking")
    open_account = await account_factory(user, name="New Checking")
    await seed_balance_factory(open_account["id"], 55_000)
    await _close(supabase, closed_account["id"])

    context = await build_context_for_user(user, supabase)
    result = await GetBalanceTool(supabase).execute(
        ToolCall(id="c1", name="get_balance", arguments={}), context
    )

    assert result.ok, result.error
    assert result.data["account_id"] == str(open_account["id"])
    assert result.data["balance_minor"] == 55_000
