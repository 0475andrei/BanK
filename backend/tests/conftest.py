"""Shared fixtures.

Tests run directly against the REAL hosted Supabase project, over HTTPS -
this machine's network blocks direct Postgres ports (5432/6543), and there
is no local database anywhere in this app anymore (see the Supabase REST
migration notes in docs/AUTH_HANDOFF.md). The concurrency tests still prove
real row-locking: Postgres still applies `FOR UPDATE` for real inside the
post_transaction/create_transfer RPC functions, just reached over
REST/RPC instead of a direct connection - the guarantee itself doesn't
depend on how the app talks to Postgres.

WARNING: `clean_db` deletes every row from every table before each test,
against whatever project SUPABASE_URL/SUPABASE_KEY point at. Never point
this at a project you want to keep data in.

Auth note: tests authenticate by writing a `sessions` row directly and
setting the cookie by hand, using exactly the primitives core/security.py +
core/dependencies.py define - proving those primitives are a self-contained
contract that doesn't require going through the login endpoint.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport
from httpx import AsyncClient as HTTPXAsyncClient
from supabase import AsyncClient, acreate_client

from app.config import settings
from app.core.security import generate_session_token, hash_password, hash_session_token
from app.db.supabase_client import get_supabase
from app.main import create_app
from app.modules.users.schemas import UserRead

# Children-before-parents, respects the ON DELETE RESTRICT constraints.
_TABLES_IN_FK_ORDER = (
    "sessions",
    "login_attempts",
    "card_orders",
    "cards",
    "transfers",
    "ledger_entries",
    "journal_transactions",
    "audit_log",
    "accounts",
    "users",
)

# PostgREST rejects an unconditional DELETE; this filter matches every real
# row since no id is ever the nil UUID.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"


@pytest_asyncio.fixture
async def supabase() -> AsyncIterator[AsyncClient]:
    """Function-scoped (not session-scoped): pytest-asyncio gives each test
    function its own event loop by default, and an AsyncClient created
    against one loop breaks ("Event loop is closed") once reused from a
    later test's different loop. A fresh client per test avoids that."""
    client = await acreate_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    yield client


@pytest_asyncio.fixture(autouse=True)
async def clean_db(supabase: AsyncClient) -> None:
    """Runs before every test: empties every table (child tables first)."""
    for table in _TABLES_IN_FK_ORDER:
        await supabase.table(table).delete().neq("id", _NIL_UUID).execute()


@pytest.fixture
def app(supabase: AsyncClient):
    async def override_get_supabase() -> AsyncIterator[AsyncClient]:
        yield supabase

    application = create_app()
    application.dependency_overrides[get_supabase] = override_get_supabase
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[HTTPXAsyncClient]:
    transport = ASGITransport(app=app)
    async with HTTPXAsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_factory(supabase: AsyncClient) -> Callable[..., Awaitable[UserRead]]:
    async def _factory(
        email: str | None = None, first_name: str = "Test", last_name: str = "User"
    ) -> UserRead:
        email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
        resp = (
            await supabase.table("users")
            .insert(
                {
                    "email": email,
                    "password_hash": hash_password("password123"),
                    "first_name": first_name,
                    "last_name": last_name,
                }
            )
            .execute()
        )
        return UserRead.model_validate(resp.data[0])

    return _factory


@pytest.fixture
def session_token_factory(supabase: AsyncClient) -> Callable[..., Awaitable[str]]:
    async def _factory(user: UserRead, *, expired: bool = False) -> str:
        token = generate_session_token()
        delta = timedelta(days=-1) if expired else timedelta(seconds=settings.SESSION_TTL_SECONDS)
        await supabase.table("sessions").insert(
            {
                "user_id": str(user.id),
                "token_hash": hash_session_token(token),
                "expires_at": (datetime.now(UTC) + delta).isoformat(),
            }
        ).execute()
        return token

    return _factory


@pytest.fixture
def account_factory(supabase: AsyncClient) -> Callable[..., Awaitable[dict]]:
    async def _factory(user: UserRead, name: str = "Account", currency: str = "USD") -> dict:
        resp = (
            await supabase.table("accounts")
            .insert(
                {
                    "user_id": str(user.id),
                    "name": name,
                    "currency": currency,
                    "status": "active",
                }
            )
            .execute()
        )
        return resp.data[0]

    return _factory


@pytest.fixture
def seed_balance_factory(supabase: AsyncClient) -> Callable[..., Awaitable[None]]:
    """TEST-ONLY: credits an account directly via a single-sided ledger
    entry, bypassing post_transaction's debit/credit balance check.

    There is currently no deposit/external-funding concept anywhere in
    flow.md's schema or module list - the spec only covers MOVEMENT of
    money between accounts, not how it enters the system - and
    post_transaction would reject debiting a zero-balance "funding"
    account anyway (insufficient funds). So this is the only way to give a
    test account an opening balance. It is never used by application code.
    """

    async def _seed(account_id: uuid.UUID | str, amount_minor: int, currency: str = "USD") -> None:
        journal = (
            await supabase.table("journal_transactions")
            .insert(
                {
                    "reference": "TEST-SEED",
                    "idempotency_key": f"test-seed-{uuid.uuid4()}",
                    "description": "Test fixture seed balance",
                }
            )
            .execute()
        ).data[0]
        await supabase.table("ledger_entries").insert(
            {
                "journal_id": journal["id"],
                "account_id": str(account_id),
                "direction": "credit",
                "amount_minor": amount_minor,
                "currency": currency,
            }
        ).execute()

    return _seed


@pytest_asyncio.fixture
async def authed_client_factory(app, user_factory, session_token_factory):
    """For tests that need more than one identity (e.g. proving user A
    can't see user B's accounts). Each call spins up its own AsyncClient
    (own cookie jar) logged in as a fresh user, unless one is passed in."""
    clients: list[HTTPXAsyncClient] = []

    async def _make(user: UserRead | None = None) -> tuple[HTTPXAsyncClient, UserRead]:
        if user is None:
            user = await user_factory()
        token = await session_token_factory(user)
        transport = ASGITransport(app=app)
        ac = HTTPXAsyncClient(transport=transport, base_url="http://test")
        ac.cookies.set(settings.SESSION_COOKIE_NAME, token)
        clients.append(ac)
        return ac, user

    yield _make

    for ac in clients:
        await ac.aclose()


@pytest_asyncio.fixture
async def authed_client(authed_client_factory) -> tuple[HTTPXAsyncClient, UserRead]:
    return await authed_client_factory()
