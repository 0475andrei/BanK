import uuid

from supabase import AsyncClient

from app.modules.users.schemas import UserRead


async def upsert_beneficiary(
    supabase: AsyncClient, *, user_id: uuid.UUID, iban: str, display_name: str
) -> dict:
    """Called after a payment succeeds (see payments/service.py) - saving a
    contact is a side effect of paying someone, not a separate flow, per the
    "keep the contacts after entering each other's iban and data" ask."""
    resp = (
        await supabase.table("beneficiaries")
        .upsert(
            {"user_id": str(user_id), "iban": iban, "display_name": display_name},
            on_conflict="user_id,iban",
        )
        .execute()
    )
    return resp.data[0]


async def list_beneficiaries(supabase: AsyncClient, user: UserRead) -> list[dict]:
    resp = (
        await supabase.table("beneficiaries")
        .select("*")
        .eq("user_id", str(user.id))
        .order("display_name")
        .execute()
    )
    return resp.data
