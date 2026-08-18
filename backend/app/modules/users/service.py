from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.modules.users.models import User
from app.modules.users.schemas import UserUpdate


async def update_profile(db: AsyncSession, user: User, payload: UserUpdate) -> User:
    if payload.full_name is not None:
        user.full_name = payload.full_name
        await db.flush()
        await record_audit_event(
            db, user_id=user.id, action="users.update_profile", entity=f"users:{user.id}"
        )
    return user
