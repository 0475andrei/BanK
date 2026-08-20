"""Registration, login, logout. Session mechanics (the cookie, the token
hashing) are core/security.py + core/dependencies.py, documented in
docs/AUTH_HANDOFF.md - this module is the producer side: it's the only
code that ever writes to `sessions`.
"""

import uuid
from datetime import UTC, datetime, timedelta

from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.config import settings
from app.core.audit import record_audit_event
from app.core.exceptions import (
    EmailAlreadyRegisteredError,
    InvalidResetCodeError,
    LoginRateLimitedError,
    NationalIdAlreadyRegisteredError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import (
    generate_otp_code,
    generate_session_token,
    hash_otp_code,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.core.teams import send_teams_message
from app.modules.auth.schemas import LoginRequest, RegisterRequest, ResetPasswordRequest
from app.modules.auth.validation import (
    extract_date_of_birth,
    extract_gender,
    validate_national_id,
)
from app.modules.users.schemas import UserRead

LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW_MINUTES = 15

RESET_CODE_TTL_MINUTES = 10
RESET_CODE_MAX_ATTEMPTS = 5

UNIQUE_VIOLATION = "23505"

# Optional at registration - entering it is what unlocks the welcome
# balance on accounts (see accounts/service.py::OPENING_BALANCE_MINOR).
# Case-insensitive so "bankTHA"/"BANKTHA"/etc all count.
REFERRAL_CODE = "BanKTHA"


def _is_referral_code_valid(referral_code: str | None) -> bool:
    return referral_code is not None and referral_code.strip().lower() == REFERRAL_CODE.lower()


async def start_session(supabase: AsyncClient, user: UserRead) -> str:
    """Creates a session row and returns the raw token to put in the
    cookie. Shared by register (auto-login) and login."""
    token = generate_session_token()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.SESSION_TTL_SECONDS)
    await supabase.table("sessions").insert(
        {
            "user_id": str(user.id),
            "token_hash": hash_session_token(token),
            "expires_at": expires_at.isoformat(),
        }
    ).execute()
    return token


def _duplicate_registration_error(exc: APIError) -> Exception:
    detail = f"{exc.message} {exc.details or ''}".lower()
    if "national_id" in detail:
        return NationalIdAlreadyRegisteredError()
    return EmailAlreadyRegisteredError()


async def register_user(supabase: AsyncClient, payload: RegisterRequest) -> tuple[UserRead, str]:
    is_valid, reason = validate_national_id(payload.national_id)
    if not is_valid:
        raise ValidationError(reason)

    try:
        resp = (
            await supabase.table("users")
            .insert(
                {
                    "email": payload.email.lower(),
                    "password_hash": hash_password(payload.password),
                    "first_name": payload.first_name.strip(),
                    "last_name": payload.last_name.strip(),
                    "national_id": payload.national_id,
                    "gender": extract_gender(payload.national_id),
                    "date_of_birth": extract_date_of_birth(payload.national_id).isoformat(),
                    "phone": payload.phone,
                    "address": payload.address,
                    "referral_bonus_eligible": _is_referral_code_valid(payload.referral_code),
                }
            )
            .execute()
        )
    except APIError as exc:
        if exc.code == UNIQUE_VIOLATION:
            raise _duplicate_registration_error(exc) from exc
        raise

    user = UserRead.model_validate(resp.data[0])

    await record_audit_event(
        supabase, user_id=user.id, action="auth.register", entity=f"users:{user.id}"
    )

    token = await start_session(supabase, user)
    return user, token


async def _count_recent_failed_attempts(supabase: AsyncClient, email: str) -> int:
    window_start = datetime.now(UTC) - timedelta(minutes=LOGIN_LOCKOUT_WINDOW_MINUTES)
    resp = (
        await supabase.table("login_attempts")
        .select("id", count="exact")
        .eq("email", email)
        .eq("success", False)
        .gte("created_at", window_start.isoformat())
        .execute()
    )
    return resp.count or 0


async def login_user(supabase: AsyncClient, payload: LoginRequest) -> tuple[UserRead, str]:
    email = payload.email.lower()

    if await _count_recent_failed_attempts(supabase, email) >= LOGIN_MAX_FAILED_ATTEMPTS:
        raise LoginRateLimitedError()

    resp = await supabase.table("users").select("*").eq("email", email).maybe_single().execute()
    user_row = resp.data if resp is not None else None

    # Same error whether the email doesn't exist or the password is wrong -
    # don't leak which one it is (avoids user enumeration).
    if user_row is None or not verify_password(payload.password, user_row["password_hash"]):
        await supabase.table("login_attempts").insert({"email": email, "success": False}).execute()
        # Each REST call is already its own committed statement (unlike the
        # old SQLAlchemy request-scoped transaction), so unlike the previous
        # version there's no ambient transaction that could roll this
        # failure-log insert back - no explicit commit needed here.
        raise UnauthorizedError("Invalid email or password.")

    user = UserRead.model_validate(user_row)

    await supabase.table("login_attempts").insert({"email": email, "success": True}).execute()
    await record_audit_event(
        supabase, user_id=user.id, action="auth.login", entity=f"users:{user.id}"
    )

    token = await start_session(supabase, user)
    return user, token


async def request_password_reset(supabase: AsyncClient, email: str) -> None:
    """Always completes normally, whether or not the email is registered -
    the caller (router) must not be able to tell the two cases apart, or
    this becomes a user-enumeration oracle. If the user exists: any prior
    unconsumed code is invalidated, a fresh one is generated, stored (hash
    only), and best-effort delivered to Teams. A Teams outage never surfaces
    here - see core/teams.py."""
    email = email.lower()
    resp = await supabase.table("users").select("id").eq("email", email).maybe_single().execute()
    user_row = resp.data if resp is not None else None
    if user_row is None:
        return
    user_id = user_row["id"]

    # At most one live code per user - an old, still-unconsumed code from a
    # previous request shouldn't keep working once a new one is issued.
    await (
        supabase.table("password_reset_codes")
        .update({"consumed_at": datetime.now(UTC).isoformat()})
        .eq("user_id", user_id)
        .is_("consumed_at", "null")
        .execute()
    )

    code = generate_otp_code()
    expires_at = datetime.now(UTC) + timedelta(minutes=RESET_CODE_TTL_MINUTES)
    await supabase.table("password_reset_codes").insert(
        {
            "user_id": user_id,
            "code_hash": hash_otp_code(code),
            "expires_at": expires_at.isoformat(),
        }
    ).execute()

    await send_teams_message(
        f"🔐 Cod resetare parolă BanK pentru {email}: **{code}**  \n"
        f"Valabil {RESET_CODE_TTL_MINUTES} minute."
    )

    await record_audit_event(
        supabase, user_id=uuid.UUID(user_id), action="auth.request_password_reset", entity=f"users:{user_id}"
    )


async def reset_password(supabase: AsyncClient, payload: ResetPasswordRequest) -> None:
    email = payload.email.lower()
    resp = await supabase.table("users").select("id").eq("email", email).maybe_single().execute()
    user_row = resp.data if resp is not None else None
    # Same generic error whether the email is unknown, the code is wrong, or
    # it expired - never confirm which one it was (see request_password_reset).
    if user_row is None:
        raise InvalidResetCodeError()
    user_id = user_row["id"]

    resp = (
        await supabase.table("password_reset_codes")
        .select("*")
        .eq("user_id", user_id)
        .is_("consumed_at", "null")
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    )
    code_row = resp.data if resp is not None else None
    if code_row is None or code_row["attempts"] >= RESET_CODE_MAX_ATTEMPTS:
        raise InvalidResetCodeError()

    expires_at = datetime.fromisoformat(code_row["expires_at"])
    if datetime.now(UTC) >= expires_at or hash_otp_code(payload.code) != code_row["code_hash"]:
        await (
            supabase.table("password_reset_codes")
            .update({"attempts": code_row["attempts"] + 1})
            .eq("id", code_row["id"])
            .execute()
        )
        raise InvalidResetCodeError()

    await supabase.table("users").update(
        {"password_hash": hash_password(payload.new_password)}
    ).eq("id", user_id).execute()

    await (
        supabase.table("password_reset_codes")
        .update({"consumed_at": datetime.now(UTC).isoformat()})
        .eq("id", code_row["id"])
        .execute()
    )

    # A reset invalidates every existing session, on every device - the same
    # way a real bank would treat "someone just changed this password".
    await supabase.table("sessions").delete().eq("user_id", user_id).execute()

    await record_audit_event(
        supabase, user_id=uuid.UUID(user_id), action="auth.reset_password", entity=f"users:{user_id}"
    )


async def logout_user(supabase: AsyncClient, user: UserRead, token: str | None) -> None:
    if token:
        await supabase.table("sessions").delete().eq(
            "token_hash", hash_session_token(token)
        ).execute()
    await record_audit_event(
        supabase, user_id=user.id, action="auth.logout", entity=f"users:{user.id}"
    )
