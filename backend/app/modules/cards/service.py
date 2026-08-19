import uuid

from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.core.exceptions import AccountClosedError, NotFoundError
from app.modules.accounts import service as accounts_service
from app.modules.accounts.models import AccountStatus
from app.modules.cards.card_numbers import generate_card_number
from app.modules.cards.models import CardStatus
from app.modules.cards.schemas import CardCreate
from app.modules.users.schemas import UserRead


async def issue_card(supabase: AsyncClient, user: UserRead, payload: CardCreate) -> tuple[dict, str]:
    account = await accounts_service.get_account(supabase, user, payload.account_id)
    if account["status"] != AccountStatus.ACTIVE.value:
        raise AccountClosedError("Cannot issue a card for a closed account.")

    card_number = generate_card_number()
    resp = (
        await supabase.table("cards")
        .insert(
            {
                "account_id": str(account["id"]),
                "last4": card_number[-4:],
                "status": CardStatus.ACTIVE.value,
                "spending_limit_minor": payload.spending_limit_minor,
            }
        )
        .execute()
    )
    card = resp.data[0]

    await record_audit_event(
        supabase,
        user_id=user.id,
        action="cards.issue",
        entity=f"cards:{card['id']}",
        metadata={"account_id": str(account["id"])},
    )
    return card, card_number


async def list_cards(supabase: AsyncClient, user: UserRead) -> list[dict]:
    # Safe two-call fallback instead of relying on PostgREST's embedded-
    # filter syntax (unstable across versions) - not a hot/concurrent path.
    accounts_resp = (
        await supabase.table("accounts").select("id").eq("user_id", str(user.id)).execute()
    )
    account_ids = [row["id"] for row in accounts_resp.data]
    if not account_ids:
        return []

    resp = (
        await supabase.table("cards")
        .select("*")
        .in_("account_id", account_ids)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data


async def cancel_card(supabase: AsyncClient, user: UserRead, card_id: uuid.UUID) -> dict:
    resp = (
        await supabase.table("cards").select("*").eq("id", str(card_id)).maybe_single().execute()
    )
    card = resp.data if resp is not None else None
    if card is None:
        raise NotFoundError("Card not found.")

    account_resp = (
        await supabase.table("accounts")
        .select("id")
        .eq("id", card["account_id"])
        .eq("user_id", str(user.id))
        .maybe_single()
        .execute()
    )
    if account_resp is None or account_resp.data is None:
        raise NotFoundError("Card not found.")

    if card["status"] != CardStatus.CANCELLED.value:
        update_resp = (
            await supabase.table("cards")
            .update({"status": CardStatus.CANCELLED.value})
            .eq("id", str(card_id))
            .execute()
        )
        card = update_resp.data[0]
        await record_audit_event(
            supabase, user_id=user.id, action="cards.cancel", entity=f"cards:{card_id}"
        )

    return card
