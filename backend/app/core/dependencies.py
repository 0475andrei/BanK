"""get_supabase, get_current_user - the CONTRACT every other module builds on.

get_current_user is the read side of the session mechanism: it trusts
nothing but the hashed cookie value. It is deliberately independent of the
login/logout/register endpoints (owned by the auth teammate, see
docs/AUTH_HANDOFF.md) - anything that can insert a valid row into `sessions`
(the login endpoint, or a test fixture) can authenticate a request. This
module never writes to `sessions`, only reads.
"""

from datetime import UTC, datetime

from fastapi import Depends, Request
from supabase import AsyncClient

from app.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import hash_session_token
from app.db.supabase_client import get_supabase
from app.modules.users.schemas import UserRead

_USER_COLUMNS = (
    "id, email, first_name, last_name, email_verified, "
    "national_id, gender, date_of_birth, phone, address, "
    "referral_bonus_eligible, created_at"
)


async def get_current_user(
    request: Request,
    supabase: AsyncClient = Depends(get_supabase),
) -> UserRead:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        raise UnauthorizedError()

    token_hash = hash_session_token(token)
    resp = (
        await supabase.table("sessions")
        .select(f"expires_at, user:users({_USER_COLUMNS})")
        .eq("token_hash", token_hash)
        .maybe_single()
        .execute()
    )

    if resp is None or resp.data is None:
        raise UnauthorizedError()

    session_row = resp.data
    expires_at = datetime.fromisoformat(session_row["expires_at"])
    if expires_at <= datetime.now(UTC):
        raise UnauthorizedError("Session has expired.")

    user_row = session_row.get("user")
    if user_row is None:
        raise UnauthorizedError()

    return UserRead.model_validate(user_row)
