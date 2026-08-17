"""Shared fixtures.

Tests run against a REAL Postgres database (a "<db>_test" sibling of
DATABASE_URL's database, created on demand) rather than SQLite, because the
whole point of the concurrency tests is to exercise real row locking -
SQLite's locking model wouldn't prove anything about the actual invariant.

Auth note: the login/logout/register endpoints don't exist yet (owned by
the teammate building auth - see docs/AUTH_HANDOFF.md). Tests authenticate
by writing a `sessions` row directly and setting the cookie by hand, using
exactly the primitives core/security.py + core/dependencies.py define. This
is deliberate: it proves those primitives are a self-contained contract
that doesn't require the login endpoint to exist.
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.core.dependencies import get_db
from app.core.security import generate_session_token, hash_password, hash_session_token
from app.db import models_registry  # noqa: F401 - populates Base.metadata
from app.db.base import Base
from app.main import create_app
from app.modules.accounts.models import Account, AccountStatus
from app.modules.auth.models import UserSession
from app.modules.ledger.models import JournalTransaction, LedgerDirection, LedgerEntry
from app.modules.users.models import User


def _swap_db_name(url: str, new_db_name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{new_db_name}", parts.query, parts.fragment))


def _test_db_name(url: str) -> str:
    return f"{urlsplit(url).path.lstrip('/')}_test"


async def _ensure_database_exists(admin_url: str, db_name: str) -> None:
    admin_engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        await admin_engine.dispose()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    db_name = _test_db_name(settings.DATABASE_URL)
    admin_url = _swap_db_name(settings.DATABASE_URL, "postgres")
    await _ensure_database_exists(admin_url, db_name)

    test_url = _swap_db_name(settings.DATABASE_URL, db_name)
    engine = create_async_engine(test_url, poolclass=NullPool)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
def test_sessionmaker(test_engine):
    return async_sessionmaker(bind=test_engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_db(test_engine):
    """Runs before every test: empties every table (child tables first, per
    FK dependency order) so each test starts from a blank database without
    paying to recreate the schema each time."""
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def db(test_sessionmaker) -> AsyncIterator[AsyncSession]:
    async with test_sessionmaker() as session:
        yield session


@pytest.fixture
def app(test_sessionmaker):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with test_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    application = create_app()
    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_factory(test_sessionmaker) -> Callable[..., Awaitable[User]]:
    async def _factory(email: str | None = None, full_name: str = "Test User") -> User:
        email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
        async with test_sessionmaker() as session:
            user = User(
                email=email, password_hash=hash_password("password123"), full_name=full_name
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _factory


@pytest.fixture
def session_token_factory(test_sessionmaker) -> Callable[..., Awaitable[str]]:
    async def _factory(user: User, *, expired: bool = False) -> str:
        token = generate_session_token()
        delta = timedelta(days=-1) if expired else timedelta(seconds=settings.SESSION_TTL_SECONDS)
        async with test_sessionmaker() as session:
            session.add(
                UserSession(
                    user_id=user.id,
                    token_hash=hash_session_token(token),
                    expires_at=datetime.now(UTC) + delta,
                )
            )
            await session.commit()
        return token

    return _factory


@pytest.fixture
def account_factory(test_sessionmaker) -> Callable[..., Awaitable[Account]]:
    async def _factory(user: User, name: str = "Account", currency: str = "USD") -> Account:
        async with test_sessionmaker() as session:
            account = Account(
                user_id=user.id, name=name, currency=currency, status=AccountStatus.ACTIVE
            )
            session.add(account)
            await session.commit()
            await session.refresh(account)
            return account

    return _factory


@pytest.fixture
def seed_balance_factory(test_sessionmaker) -> Callable[..., Awaitable[None]]:
    """TEST-ONLY: credits an account directly via a single-sided ledger
    entry, bypassing post_transaction's debit/credit balance check.

    There is currently no deposit/external-funding concept anywhere in
    flow.md's schema or module list - the spec only covers MOVEMENT of
    money between accounts, not how it enters the system - and
    post_transaction would reject debiting a zero-balance "funding"
    account anyway (insufficient funds). So this is the only way to give a
    test account an opening balance. It is never used by application code;
    see docs/AUTH_HANDOFF.md's "known gaps" note.
    """

    async def _seed(account_id: uuid.UUID, amount_minor: int, currency: str = "USD") -> None:
        async with test_sessionmaker() as session:
            journal = JournalTransaction(
                reference="TEST-SEED",
                idempotency_key=f"test-seed-{uuid.uuid4()}",
                description="Test fixture seed balance",
            )
            session.add(journal)
            await session.flush()
            session.add(
                LedgerEntry(
                    journal_id=journal.id,
                    account_id=account_id,
                    direction=LedgerDirection.CREDIT,
                    amount_minor=amount_minor,
                    currency=currency,
                )
            )
            await session.commit()

    return _seed


@pytest_asyncio.fixture
async def authed_client_factory(app, user_factory, session_token_factory):
    """For tests that need more than one identity (e.g. proving user A
    can't see user B's accounts). Each call spins up its own AsyncClient
    (own cookie jar) logged in as a fresh user, unless one is passed in."""
    clients: list[AsyncClient] = []

    async def _make(user: User | None = None) -> tuple[AsyncClient, User]:
        if user is None:
            user = await user_factory()
        token = await session_token_factory(user)
        transport = ASGITransport(app=app)
        ac = AsyncClient(transport=transport, base_url="http://test")
        ac.cookies.set(settings.SESSION_COOKIE_NAME, token)
        clients.append(ac)
        return ac, user

    yield _make

    for ac in clients:
        await ac.aclose()


@pytest_asyncio.fixture
async def authed_client(authed_client_factory) -> tuple[AsyncClient, User]:
    return await authed_client_factory()
