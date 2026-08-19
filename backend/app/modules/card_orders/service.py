from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.modules.accounts import service as accounts_service
from app.modules.card_orders.schemas import CardOrderCreate
from app.modules.cards import service as cards_service
from app.modules.cards.schemas import CardCreate
from app.modules.users.schemas import UserRead


async def create_order(supabase: AsyncClient, user: UserRead, payload: CardOrderCreate) -> dict:
    account = await accounts_service.get_account(supabase, user, payload.account_id)

    card = await cards_service.issue_card(supabase, user, CardCreate(account_id=account["id"]))

    resp = (
        await supabase.table("card_orders")
        .insert(
            {
                "account_id": str(account["id"]),
                "card_id": card["id"],
                "full_name": payload.full_name,
                "phone": payload.phone,
                "address": payload.address,
                "city": payload.city,
                "postal_code": payload.postal_code,
                "country": payload.country,
            }
        )
        .execute()
    )
    order = resp.data[0]
    order["card"] = card

    await record_audit_event(
        supabase,
        user_id=user.id,
        action="card_orders.create",
        entity=f"card_orders:{order['id']}",
        metadata={"account_id": str(account["id"])},
    )
    return order


async def list_orders(supabase: AsyncClient, user: UserRead) -> list[dict]:
    # Safe two-call fallback instead of relying on PostgREST's embedded-
    # filter syntax (unstable across versions) - not a hot/concurrent path.
    # The card:cards(*) embed is a straight FK-based join, not this same
    # instability, so it's kept for the nested card details.
    accounts_resp = (
        await supabase.table("accounts").select("id").eq("user_id", str(user.id)).execute()
    )
    account_ids = [row["id"] for row in accounts_resp.data]
    if not account_ids:
        return []

    resp = (
        await supabase.table("card_orders")
        .select("*, card:cards(*)")
        .in_("account_id", account_ids)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data
