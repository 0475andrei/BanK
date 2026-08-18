"""Registration, login, logout. Session mechanics (the cookie, the token
hashing) are core/security.py + core/dependencies.py, documented in
docs/AUTH_HANDOFF.md - this module is the producer side: it's the only
code that ever writes to `sessions`.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.audit import record_audit_event
from app.core.exceptions import (
    EmailAlreadyRegisteredError,
    LoginRateLimitedError,
    NationalIdAlreadyRegisteredError,
    UnauthorizedError,
    ValidationError,
)
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.modules.auth.models import LoginAttempt, UserSession
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.validation import (
    extract_date_of_birth,
    extract_gender,
    validate_national_id,
)
from app.modules.users.models import User

LOGIN_MAX_FAILED_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW_MINUTES = 15


async def start_session(db: AsyncSession, user: User) -> str:
    """Creates a session row and returns the raw token to put in the
    cookie. Shared by register (auto-login) and login."""
    token = generate_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.SESSION_TTL_SECONDS),
        )
    )
    await db.flush()
    return token


def _duplicate_registration_error(exc: IntegrityError) -> Exception:
    constraint = (getattr(exc.orig, "constraint_name", None) or str(exc.orig)).lower()
    if "national_id" in constraint:
        return NationalIdAlreadyRegisteredError()
    return EmailAlreadyRegisteredError()


async def register_user(db: AsyncSession, payload: RegisterRequest) -> tuple[User, str]:
    is_valid, reason = validate_national_id(payload.national_id)
    if not is_valid:
        raise ValidationError(reason)

    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        national_id=payload.national_id,
        gender=extract_gender(payload.national_id),
        date_of_birth=extract_date_of_birth(payload.national_id),
        phone=payload.phone,
        address=payload.address,
    )

    try:
        async with db.begin_nested():
            db.add(user)
            await db.flush()
    except IntegrityError as exc:
        raise _duplicate_registration_error(exc) from exc

    await record_audit_event(db, user_id=user.id, action="auth.register", entity=f"users:{user.id}")

    token = await start_session(db, user)
    return user, token


async def _count_recent_failed_attempts(db: AsyncSession, email: str) -> int:
    window_start = datetime.now(UTC) - timedelta(minutes=LOGIN_LOCKOUT_WINDOW_MINUTES)
    stmt = (
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.email == email,
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= window_start,
        )
    )
    return (await db.execute(stmt)).scalar_one()


async def login_user(db: AsyncSession, payload: LoginRequest) -> tuple[User, str]:
    email = payload.email.lower()

    if await _count_recent_failed_attempts(db, email) >= LOGIN_MAX_FAILED_ATTEMPTS:
        raise LoginRateLimitedError()

    stmt = select(User).where(User.email == email)
    user = (await db.execute(stmt)).scalar_one_or_none()

    # Same error whether the email doesn't exist or the password is wrong -
    # don't leak which one it is (avoids user enumeration).
    if user is None or not verify_password(payload.password, user.password_hash):
        db.add(LoginAttempt(email=email, success=False))
        # Commit explicitly: raising UnauthorizedError next causes
        # get_db's wrapper to roll back the request's transaction, which
        # would otherwise silently discard this failure record - and with
        # it, the rate limit that depends on counting them.
        await db.commit()
        raise UnauthorizedError("Invalid email or password.")

    db.add(LoginAttempt(email=email, success=True))
    await record_audit_event(db, user_id=user.id, action="auth.login", entity=f"users:{user.id}")

    token = await start_session(db, user)
    return user, token


async def logout_user(db: AsyncSession, user: User, token: str | None) -> None:
    if token:
        stmt = select(UserSession).where(UserSession.token_hash == hash_session_token(token))
        session_row = (await db.execute(stmt)).scalar_one_or_none()
        if session_row is not None:
            await db.delete(session_row)
    await record_audit_event(db, user_id=user.id, action="auth.logout", entity=f"users:{user.id}")
