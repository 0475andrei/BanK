"""In-app notifications (the header bell icon). create_notification is the
one entry point other modules call to raise one - see accounts/service.py's
referral reward payout for the first (only, so far) caller.
"""

import uuid
from datetime import UTC, datetime

from supabase import AsyncClient

from app.modules.users.schemas import UserRead

DEFAULT_LIMIT = 20


async def create_notification(supabase: AsyncClient, user_id: uuid.UUID | str, title: str, body: str) -> dict:
    resp = (
        await supabase.table("notifications")
        .insert({"user_id": str(user_id), "title": title, "body": body})
        .execute()
    )
    return resp.data[0]


async def list_notifications(supabase: AsyncClient, user: UserRead, limit: int = DEFAULT_LIMIT) -> list[dict]:
    resp = (
        await supabase.table("notifications")
        .select("*")
        .eq("user_id", str(user.id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return resp.data


async def count_unread(supabase: AsyncClient, user: UserRead) -> int:
    resp = (
        await supabase.table("notifications")
        .select("id", count="exact")
        .eq("user_id", str(user.id))
        .is_("read_at", "null")
        .execute()
    )
    return resp.count or 0


async def mark_all_read(supabase: AsyncClient, user: UserRead) -> None:
    await (
        supabase.table("notifications")
        .update({"read_at": datetime.now(UTC).isoformat()})
        .eq("user_id", str(user.id))
        .is_("read_at", "null")
        .execute()
    )
