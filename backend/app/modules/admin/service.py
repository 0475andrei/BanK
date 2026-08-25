"""Admin reads across every user, plus card-order fulfilment.

NOTE ON SCOPING: unlike every other service module, nothing here filters by
the caller's user id. That is intentional and is exactly why the router gates
the whole module behind `require_admin`.

Reads select only the columns the response schemas need, rather than `*`, so
a row's secrets (password_hash, card PAN/CVV, face embeddings) are never even
loaded into the process - defence in depth behind the schema projections in
schemas.py.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.core.exceptions import ForbiddenError, NotFoundError
from app.modules.card_orders.models import CardOrderStatus
from app.modules.ledger import service as ledger_service
from app.modules.users.schemas import UserRead

_USER_LIST_COLUMNS = (
    "id, email, first_name, last_name, role, email_verified, created_at, blocked_at"
)
_USER_DETAIL_COLUMNS = _USER_LIST_COLUMNS + ", phone, address, national_id"
#: Never card_number / cvv / expiry_month / expiry_year - see schemas.py.
_CARD_COLUMNS = "id, account_id, last4, status, spending_limit_minor"
_ACCOUNT_COLUMNS = "id, name, currency, status, iban"

#: PostgREST parses filter values as part of a comma-separated expression, so
#: a search term containing any of these would change the filter's structure
#: rather than being matched literally. Stripped instead of escaped: this is a
#: free-text search box, so dropping punctuation costs nothing and leaves no
#: room for a half-right escaping rule.
_UNSAFE_FILTER_CHARS = re.compile(r"[,()*\\.:\"']")
_MAX_SEARCH_LENGTH = 100


def _sanitize_search(term: str) -> str:
    return _UNSAFE_FILTER_CHARS.sub(" ", term).strip()[:_MAX_SEARCH_LENGTH]


async def _require_user(supabase: AsyncClient, user_id: uuid.UUID) -> dict:
    """Load a user or 404. Every write below goes through this first, so
    "no such user" is a clean 404 rather than a silent no-op update."""
    resp = (
        await supabase.table("users")
        .select(_USER_DETAIL_COLUMNS)
        .eq("id", str(user_id))
        .maybe_single()
        .execute()
    )
    user = resp.data if resp is not None else None
    if user is None:
        raise NotFoundError("User not found.")
    return user


async def list_users(
    supabase: AsyncClient,
    *,
    search: str | None = None,
    limit: int,
    offset: int,
) -> list[dict]:
    query = supabase.table("users").select(_USER_LIST_COLUMNS)

    if search:
        cleaned = _sanitize_search(search)
        if cleaned:
            pattern = f"*{cleaned}*"
            query = query.or_(
                f"email.ilike.{pattern},"
                f"first_name.ilike.{pattern},"
                f"last_name.ilike.{pattern}"
            )

    resp = (
        await query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


async def get_user_detail(supabase: AsyncClient, user_id: uuid.UUID) -> dict:
    user = await _require_user(supabase, user_id)

    accounts_resp = (
        await supabase.table("accounts")
        .select(_ACCOUNT_COLUMNS)
        .eq("user_id", str(user_id))
        .order("created_at")
        .execute()
    )
    accounts = accounts_resp.data or []

    # One balance call per account. N+1, but bounded by how many accounts a
    # single person holds (a handful) - unlike the dashboard totals, which
    # span every account and therefore use an RPC instead.
    for account in accounts:
        account["balance_minor"] = await ledger_service.get_balance(
            supabase, uuid.UUID(str(account["id"]))
        )

    cards: list[dict] = []
    if accounts:
        cards_resp = (
            await supabase.table("cards")
            .select(_CARD_COLUMNS)
            .in_("account_id", [str(a["id"]) for a in accounts])
            .execute()
        )
        cards = cards_resp.data or []

    user["accounts"] = accounts
    user["cards"] = cards
    return user


async def set_user_role(
    supabase: AsyncClient,
    admin: UserRead,
    user_id: uuid.UUID,
    role: str,
) -> dict:
    """Promote to admin or demote to customer.

    SELF-CHANGE IS REFUSED. Two reasons, and the second is the important one:
    a demotion would lock the acting admin out of the panel they are standing
    in, and more to the point, "an admin can only ever change SOMEONE ELSE's
    role" means the last remaining admin cannot quietly remove themselves and
    leave the system with none - promoting a replacement first is forced.
    Recovery from zero admins would need direct database access.
    """
    if str(user_id) == str(admin.id):
        raise ForbiddenError("You cannot change your own role.")

    target = await _require_user(supabase, user_id)

    resp = (
        await supabase.table("users")
        .update({"role": role})
        .eq("id", str(user_id))
        .execute()
    )

    await record_audit_event(
        supabase,
        user_id=admin.id,
        action="admin.set_user_role",
        entity=f"users:{user_id}",
        metadata={"from": target.get("role"), "to": role},
    )
    return resp.data[0]


async def set_user_blocked(
    supabase: AsyncClient,
    admin: UserRead,
    user_id: uuid.UUID,
    blocked: bool,
) -> dict:
    """Block or unblock an account.

    Blocking does two things, and both matter:

    1. Stamps `blocked_at`, which core/dependencies.py::get_current_user and
       auth/service.py::start_session both refuse on - so no new session can
       be created and no existing one can be used.
    2. Deletes the user's existing session rows, so they are logged out at
       once instead of merely being refused on their next request.

    Step 1 is what actually enforces it; step 2 is hygiene, and is why the
    order matters - stamp first, then clear, so a session created in the gap
    is still dead on arrival.

    Self-blocking is refused for the same reason self-demotion is.
    """
    if str(user_id) == str(admin.id):
        raise ForbiddenError("You cannot block your own account.")

    await _require_user(supabase, user_id)
    blocked_at = datetime.now(UTC).isoformat() if blocked else None

    resp = (
        await supabase.table("users")
        .update({"blocked_at": blocked_at})
        .eq("id", str(user_id))
        .execute()
    )

    if blocked:
        await supabase.table("sessions").delete().eq("user_id", str(user_id)).execute()

    await record_audit_event(
        supabase,
        user_id=admin.id,
        action="admin.block_user" if blocked else "admin.unblock_user",
        entity=f"users:{user_id}",
    )
    return resp.data[0]


async def list_user_transactions(
    supabase: AsyncClient,
    user_id: uuid.UUID,
    *,
    card_id: uuid.UUID | None = None,
    limit: int,
    offset: int,
) -> list[dict]:
    """Ledger activity for one user, optionally narrowed to a single card.

    Scoped by the user's OWN accounts first, so a card id belonging to
    someone else narrows the result to nothing rather than reaching across
    users - the admin is allowed to look at anyone, but "user X's
    transactions" must still mean X's.
    """
    await _require_user(supabase, user_id)

    accounts_resp = (
        await supabase.table("accounts")
        .select("id, name")
        .eq("user_id", str(user_id))
        .execute()
    )
    accounts = accounts_resp.data or []
    if not accounts:
        return []
    account_names = {row["id"]: row["name"] for row in accounts}

    query = (
        supabase.table("ledger_entries")
        .select("*, journal:journal_transactions(description, reference), card:cards(last4)")
        .in_("account_id", list(account_names))
    )
    if card_id is not None:
        query = query.eq("card_id", str(card_id))

    resp = (
        await query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    entries = []
    for row in resp.data or []:
        journal = row.get("journal") or {}
        card = row.get("card") or {}
        entries.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "account_id": row["account_id"],
                "account_name": account_names.get(row["account_id"]),
                "direction": row["direction"],
                "amount_minor": row["amount_minor"],
                "currency": row["currency"],
                "description": journal.get("description"),
                "reference": journal.get("reference"),
                "card_id": row.get("card_id"),
                "card_last4": card.get("last4"),
            }
        )
    return entries


async def list_card_orders(
    supabase: AsyncClient,
    *,
    status: str | None = None,
    limit: int,
    offset: int,
) -> list[dict]:
    query = supabase.table("card_orders").select("*")
    if status:
        query = query.eq("status", status)

    resp = (
        await query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    orders = resp.data or []
    if not orders:
        return []

    # card_orders has no user_id - ownership runs order -> account -> user.
    # Resolved in two flat lookups rather than a nested PostgREST embed, the
    # same caution card_orders/service.py::list_orders documents.
    account_ids = {str(o["account_id"]) for o in orders}
    accounts_resp = (
        await supabase.table("accounts")
        .select("id, user_id")
        .in_("id", list(account_ids))
        .execute()
    )
    account_to_user = {row["id"]: row["user_id"] for row in (accounts_resp.data or [])}

    emails: dict[str, str] = {}
    user_ids = {uid for uid in account_to_user.values() if uid}
    if user_ids:
        users_resp = (
            await supabase.table("users")
            .select("id, email")
            .in_("id", list(user_ids))
            .execute()
        )
        emails = {row["id"]: row["email"] for row in (users_resp.data or [])}

    for order in orders:
        owner_id = account_to_user.get(str(order["account_id"]))
        order["user_id"] = owner_id
        order["user_email"] = emails.get(owner_id) if owner_id else None
    return orders


async def update_card_order_status(
    supabase: AsyncClient,
    admin: UserRead,
    order_id: uuid.UUID,
    status: str,
) -> dict:
    """The panel's only write. Nothing else here changes state.

    Deliberately does not touch the linked card: cancelling an ORDER means
    "this piece of plastic is not being posted", which is not the same as
    cancelling the card itself (that is irreversible - see
    cards/service.py::cancel_card - and stays a customer decision).
    """
    existing_resp = (
        await supabase.table("card_orders")
        .select("id, status")
        .eq("id", str(order_id))
        .maybe_single()
        .execute()
    )
    existing = existing_resp.data if existing_resp is not None else None
    if existing is None:
        raise NotFoundError("Card order not found.")

    resp = (
        await supabase.table("card_orders")
        .update({"status": status})
        .eq("id", str(order_id))
        .execute()
    )
    updated = resp.data[0]

    # The admin's own id, not the order owner's: the audit trail answers
    # "who did this", and the actor here is the admin.
    await record_audit_event(
        supabase,
        user_id=admin.id,
        action="admin.card_order_status",
        entity=f"card_orders:{order_id}",
        metadata={"from": existing["status"], "to": status},
    )
    return updated


async def list_audit_log(
    supabase: AsyncClient,
    *,
    user_id: uuid.UUID | None = None,
    action: str | None = None,
    limit: int,
    offset: int,
) -> list[dict]:
    query = supabase.table("audit_log").select("*")
    if user_id is not None:
        query = query.eq("user_id", str(user_id))
    if action:
        cleaned = _sanitize_search(action)
        if cleaned:
            query = query.ilike("action", f"*{cleaned}*")

    resp = (
        await query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return resp.data or []


async def _count(supabase: AsyncClient, table: str, **filters: str) -> int:
    """Row count without pulling the rows: PostgREST returns it in the
    Content-Range header, which supabase-py surfaces as `.count`."""
    query = supabase.table(table).select("id", count="exact")
    for column, value in filters.items():
        query = query.eq(column, value)
    resp = await query.limit(1).execute()
    return resp.count or 0


async def get_stats(supabase: AsyncClient) -> dict[str, Any]:
    totals_resp = await supabase.rpc("admin_totals_by_currency", {}).execute()
    return {
        "total_users": await _count(supabase, "users"),
        "total_accounts": await _count(supabase, "accounts"),
        "total_cards": await _count(supabase, "cards"),
        "pending_card_orders": await _count(
            supabase, "card_orders", status=CardOrderStatus.PENDING.value
        ),
        "totals_by_currency": totals_resp.data or [],
    }
