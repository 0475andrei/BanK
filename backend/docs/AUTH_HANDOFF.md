# Auth handoff — context for building `modules/auth`

This is for whoever (and whichever Claude Code session) builds login,
logout, and registration. It explains exactly what already exists, what
you're building, and the contract between the two, so you don't have to
reverse-engineer it from the diff.

Read `flow.md` at the repo root first for the overall project spec. This
document only covers the auth boundary.

## Where things stand

Person A's side of `backend/` is implemented and tested: Docker/Postgres
setup, `core/` (money, security primitives, idempotency, exceptions, audit,
middleware, `get_db`/`get_current_user`), the ledger (`post_transaction`),
accounts, transfers, users (profile read/update), and transaction history.
44 tests pass (unit + integration, including concurrent-transfer and
idempotency proofs) against real Postgres.

**Deliberately not built: `app/modules/auth/router.py`, `service.py`,
`schemas.py`.** That's this handoff's subject. Everything else in
`app/modules/auth/` — just `models.py` — already exists, because
`core/dependencies.py::get_current_user` (which every protected endpoint in
the app depends on) needs the `sessions` table to query. See "The contract"
below for exactly what's there and how to use it.

## The contract

### Database (already migrated, don't recreate)

```
users
  id (UUID pk), email (unique), password_hash, full_name, created_at

sessions   -- ORM class name is UserSession, not Session (see why below)
  id (UUID pk), user_id -> users.id (CASCADE), token_hash (unique),
  expires_at (TIMESTAMPTZ), created_at
```

Models: `app/modules/users/models.py::User`,
`app/modules/auth/models.py::UserSession`. Named `UserSession` (table is
still `sessions`) to avoid colliding with `sqlalchemy.orm.Session` /
`AsyncSession` in files that import both — use that name when you import
it.

The initial Alembic migration (`app/db/migrations/versions/*_initial_schema.py`)
already created both tables. You won't need a new migration unless you add
columns (e.g. if you want an `is_active` flag or similar) — if so, run
`alembic revision --autogenerate -m "..."` the same way the initial one was
generated (see "Dev workflow" below); autogenerate will pick up your
changes because `app/db/models_registry.py` already imports both models.

### `app/core/security.py` — primitives you call, don't reimplement

```python
hash_password(password: str) -> str
verify_password(password: str, password_hash: str) -> bool
generate_session_token() -> str      # raw token -> goes in the cookie
hash_session_token(token: str) -> str  # sha256 hex -> goes in sessions.token_hash
```

Session design: the cookie carries one opaque random token. It is **never**
stored raw — only `hash_session_token(token)` goes in the DB, the same
"store a hash, not the secret" pattern as passwords (SHA-256 here, not
bcrypt, because the token already has 256 bits of entropy — there's nothing
for a slow KDF to protect against). This means:

- **Login**: verify credentials, then `token = generate_session_token()`,
  insert a `UserSession(token_hash=hash_session_token(token), ...)`, and put
  the *raw* `token` in the cookie. That's the only moment the raw token
  exists outside the client's cookie jar.
- **Logout**: hash the cookie's token, delete the matching row.

### `app/core/dependencies.py::get_current_user` — the read side, already done

```python
async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
```

Reads `request.cookies[settings.SESSION_COOKIE_NAME]`, hashes it, looks up
`sessions.token_hash`, checks `expires_at`, returns the `User` (via an
eager-loaded relationship, so no extra query). Raises `UnauthorizedError`
(401) for: no cookie, unknown token, expired session. **You never call this
directly** — every protected route already depends on it. Your job is only
to make sure a valid row ends up in `sessions` and the cookie ends up in
the client's browser; this function does the rest.

It never writes to `sessions`, only reads — so it has zero coupling to how
you implement login. That's also why the test suite could authenticate
without your endpoints existing yet: `tests/conftest.py`'s
`user_factory`/`session_token_factory` fixtures insert directly using these
same primitives. Those fixtures remain valid after you build real login —
other modules' tests use them for cheap setup, not to exercise login
itself.

### Config (`app/config.py`)

```python
SESSION_COOKIE_NAME: str = "session_token"
SESSION_TTL_SECONDS: int = 60 * 60 * 24 * 7   # 7 days
```

Use `settings.SESSION_COOKIE_NAME` and `settings.SESSION_TTL_SECONDS` —
don't hard-code the cookie name or a duration. `settings.is_production` is
available if you want `secure=True` on the cookie only outside dev.

## What you're building

`app/modules/auth/schemas.py`, `service.py`, `router.py` — same
models.py/schemas.py/service.py/router.py layout every other module uses
(e.g. look at `app/modules/transfers/` for the pattern: schemas are plain
Pydantic, service.py takes `db` + validated input and does the work,
router.py is thin and just wires `Depends()` to service calls).

Suggested endpoints (adjust freely — this isn't dictated by the schema,
just a reasonable shape):

- `POST /api/v1/auth/register` — create a `User` (hash the password with
  `hash_password`), then log them in (same as login, below).
- `POST /api/v1/auth/login` — verify credentials, create a session, set the
  cookie.
- `POST /api/v1/auth/logout` — delete the session row, clear the cookie.
  Needs `get_current_user` (or just read+hash the cookie yourself) to know
  which session to delete.

None of these are money-moving endpoints, so **no `Idempotency-Key`** is
needed (that mechanism — `core/idempotency.py` — is specific to
transfers/payments/cards/etc. per flow.md rule #5).

### Setting/clearing the cookie — the one FastAPI gotcha

To set cookies while still returning a Pydantic `response_model`, inject
`Response` as a parameter and mutate it — FastAPI merges its headers into
the real response:

```python
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_current_user, get_db
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)
from app.modules.auth.models import UserSession
from app.modules.users.models import User

router = APIRouter()


async def _start_session(db: AsyncSession, response: Response, user: User) -> None:
    token = generate_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.SESSION_TTL_SECONDS),
        )
    )
    await db.flush()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.SESSION_TTL_SECONDS,
    )


@router.post("/login", response_model=UserRead)  # UserRead from users/schemas.py
async def login(
    payload: LoginRequest,  # your schema: email + password
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    stmt = select(User).where(User.email == payload.email.lower())
    user = (await db.execute(stmt)).scalar_one_or_none()
    # Same error for "no such email" and "wrong password" - don't leak
    # which one it is (avoids user enumeration).
    if user is None or not verify_password(payload.password, user.password_hash):
        raise UnauthorizedError("Invalid email or password.")
    await _start_session(db, response, user)
    return user


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),  # 401s if already not logged in
) -> None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        token_hash = hash_session_token(token)
        stmt = select(UserSession).where(UserSession.token_hash == token_hash)
        session_row = (await db.execute(stmt)).scalar_one_or_none()
        if session_row is not None:
            await db.delete(session_row)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
```

This sketch is a starting point, not a spec to match exactly — e.g. decide
for yourself whether login should revoke the user's other existing
sessions (single-session-per-user) or leave them alone (multi-device,
simpler — just insert a new row). Both are reasonable; nothing else in the
codebase assumes either way.

### Mount the router

`app/api/v1.py` already has this waiting, uncommented, as the last lines of
the file:

```python
from app.modules.auth.router import router as auth_router
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
```

### Conventions to match

- **Errors**: raise `AppError` subclasses from `app/core/exceptions.py`
  (`UnauthorizedError` for bad login, `ValidationError` for bad input).
  You'll likely want a new one for duplicate registration, e.g.:
  ```python
  class EmailAlreadyRegisteredError(AppError):
      status_code = 409
      error_code = "email_already_registered"
      default_message = "An account with this email already exists."
  ```
  (add it next to `IdempotencyKeyConflictError`, which follows the same
  pattern). `core/middleware.py` already turns any `AppError` into a
  consistent `{"error": {"code", "message"}}` JSON body — you don't need to
  handle that yourself.
- **Audit log**: call `record_audit_event` (`app/core/audit.py`) for
  `auth.login` / `auth.logout` / `auth.register`, same as `accounts.open`,
  `ledger.post_transaction`, etc. already do.
- **Password strength / email validation**: not specified anywhere in
  flow.md — your call. A minimum length check on register is reasonable;
  nothing downstream depends on a specific rule.

## Dev workflow

```bash
cd backend
cp .env.example .env        # start.sh does this automatically too
docker compose up -d --build
docker compose exec backend pytest -q          # full suite
docker compose exec backend ruff check .        # lint
docker compose exec backend mypy app            # types

# if you add columns to users/sessions:
docker compose exec backend alembic revision --autogenerate -m "..."
docker compose exec backend alembic upgrade head
```

`./app` and `./tests` are bind-mounted into the container, so edits on the
host show up immediately — no rebuild needed unless you change
`pyproject.toml` (new dependency) or the Dockerfile itself.

For tests: `tests/conftest.py` runs everything against a real Postgres
`<db>_test` database (not SQLite — the concurrency tests need real row
locking), truncating all tables before each test. Reuse `client`,
`user_factory`, `db` from there; add `tests/integration/test_auth_api.py`
following the pattern in `tests/integration/test_accounts_api.py`. Once
your login endpoint exists, prefer testing through it directly (real
`POST /api/v1/auth/login`, assert on `Set-Cookie`) rather than only via the
fixture shortcuts — that's the actual code path users hit.

## Known gaps worth knowing about

- **No password reset / email verification** — not in flow.md's spec at
  all; out of scope unless you're asked for it.
- **Rate limiting** is global, in-process, per-IP (`core/middleware.py`) —
  it already applies to whatever you build, but it's not brute-force-aware
  per-account. Fine for this exercise; would need Redis + per-account
  limits for anything real.
- **No "remember me" / sliding expiration** — a session is a fixed
  `SESSION_TTL_SECONDS` window from creation; logging in again just creates
  another row.
