"""get_db, get_current_user - the CONTRACT every other module builds on.

get_current_user is the read side of the session mechanism: it trusts
nothing but the hashed cookie value. It is deliberately independent of the
login/logout/register endpoints (owned by the auth teammate, see
docs/AUTH_HANDOFF.md) - anything that can insert a valid row into `sessions`
(the teammate's login endpoint, or a test fixture) can authenticate a
request. This module never writes to `sessions`, only reads.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import hash_session_token
from app.db.session import session_scope
from app.modules.auth.models import UserSession
from app.modules.users.models import User


async def get_db() -> AsyncIterator[AsyncSession]:
    async with session_scope() as session:
        yield session


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise UnauthorizedError()

    token_hash = hash_session_token(token)
    stmt = select(UserSession).where(UserSession.token_hash == token_hash)
    user_session = (await db.execute(stmt)).scalar_one_or_none()

    if user_session is None:
        raise UnauthorizedError()

    now = datetime.now(UTC)
    if user_session.expires_at <= now:
        raise UnauthorizedError("Session has expired.")

    # user_session.user is eager-loaded (relationship(lazy="joined")), so
    # this doesn't cost a second round trip.
    if user_session.user is None:
        raise UnauthorizedError()

    return user_session.user
