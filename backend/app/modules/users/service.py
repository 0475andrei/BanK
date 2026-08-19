from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.modules.users.schemas import UserRead, UserUpdate


async def update_profile(supabase: AsyncClient, user: UserRead, payload: UserUpdate) -> UserRead:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return user

    resp = await supabase.table("users").update(updates).eq("id", str(user.id)).execute()

    await record_audit_event(
        supabase,
        user_id=user.id,
        action="users.update_profile",
        entity=f"users:{user.id}",
        metadata={"fields": list(updates)},
    )
    return UserRead.model_validate(resp.data[0])
