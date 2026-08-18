from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.modules.users.models import User
from app.modules.users.schemas import UserUpdate


async def update_profile(db: AsyncSession, user: User, payload: UserUpdate) -> User:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        return user

    for field, value in updates.items():
        setattr(user, field, value)

    await db.flush()
    await record_audit_event(
        db,
        user_id=user.id,
        action="users.update_profile",
        entity=f"users:{user.id}",
        metadata={"fields": list(updates)},
    )
    return user
