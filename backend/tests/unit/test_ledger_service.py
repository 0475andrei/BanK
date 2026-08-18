import uuid

import pytest

from app.core.exceptions import (
    AccountClosedError,
    AccountNotFoundError,
    CurrencyMismatchError,
    InsufficientFundsError,
    InvalidLedgerLegsError,
)
from app.modules.accounts.models import Account, AccountStatus
from app.modules.ledger.models import LedgerDirection
from app.modules.ledger.schemas import LedgerLeg
from app.modules.ledger.service import get_balance, post_transaction


def _legs(from_id, to_id, amount_minor: int, currency: str = "USD") -> list[LedgerLeg]:
    return [
        LedgerLeg(from_id, LedgerDirection.DEBIT, amount_minor, currency),
        LedgerLeg(to_id, LedgerDirection.CREDIT, amount_minor, currency),
    ]


async def test_post_transaction_moves_balance(
    db, user_factory, account_factory, seed_balance_factory
):
    user = await user_factory()
    a = await account_factory(user, name="A")
    b = await account_factory(user, name="B")
    await seed_balance_factory(a.id, 10_000)

    journal = await post_transaction(
        db, _legs(a.id, b.id, 2_500), idempotency_key=str(uuid.uuid4()), description="test"
    )
    await db.commit()

    assert journal.id is not None
    assert await get_balance(db, a.id) == 7_500
    assert await get_balance(db, b.id) == 2_500


async def test_post_transaction_rejects_unbalanced_legs(db, user_factory, account_factory):
    user = await user_factory()
    a = await account_factory(user, name="A")
    b = await account_factory(user, name="B")

    legs = [
        LedgerLeg(a.id, LedgerDirection.DEBIT, 100, "USD"),
        LedgerLeg(b.id, LedgerDirection.CREDIT, 99, "USD"),
    ]
    with pytest.raises(InvalidLedgerLegsError):
        await post_transaction(db, legs, idempotency_key=str(uuid.uuid4()), description="bad")


async def test_post_transaction_rejects_insufficient_funds(db, user_factory, account_factory):
    user = await user_factory()
    a = await account_factory(user, name="A")
    b = await account_factory(user, name="B")

    with pytest.raises(InsufficientFundsError):
        await post_transaction(
            db, _legs(a.id, b.id, 1), idempotency_key=str(uuid.uuid4()), description="overdraft"
        )


async def test_post_transaction_rejects_currency_mismatch_with_account(
    db, user_factory, account_factory, seed_balance_factory
):
    user = await user_factory()
    a = await account_factory(user, name="A", currency="USD")
    b = await account_factory(user, name="B", currency="USD")
    await seed_balance_factory(a.id, 10_000)

    legs = [
        LedgerLeg(a.id, LedgerDirection.DEBIT, 100, "EUR"),
        LedgerLeg(b.id, LedgerDirection.CREDIT, 100, "EUR"),
    ]
    with pytest.raises(CurrencyMismatchError):
        await post_transaction(db, legs, idempotency_key=str(uuid.uuid4()), description="fx")


async def test_post_transaction_rejects_unknown_account(db, user_factory, account_factory):
    user = await user_factory()
    a = await account_factory(user, name="A")

    with pytest.raises(AccountNotFoundError):
        await post_transaction(
            db, _legs(a.id, uuid.uuid4(), 100), idempotency_key=str(uuid.uuid4()), description="x"
        )


async def test_post_transaction_rejects_closed_account(
    db, user_factory, account_factory, seed_balance_factory
):
    user = await user_factory()
    a = await account_factory(user, name="A")
    b = await account_factory(user, name="B")
    await seed_balance_factory(a.id, 10_000)

    # account_factory persisted b through its own (now-closed) session, so
    # mutating the detached `b` object directly wouldn't be seen by `db` -
    # fetch it through the session that actually runs post_transaction.
    b_row = await db.get(Account, b.id)
    b_row.status = AccountStatus.CLOSED
    await db.commit()

    with pytest.raises(AccountClosedError):
        await post_transaction(
            db, _legs(a.id, b.id, 100), idempotency_key=str(uuid.uuid4()), description="x"
        )


async def test_post_transaction_is_idempotent_on_replay(
    db, user_factory, account_factory, seed_balance_factory
):
    user = await user_factory()
    a = await account_factory(user, name="A")
    b = await account_factory(user, name="B")
    await seed_balance_factory(a.id, 10_000)

    key = str(uuid.uuid4())
    first = await post_transaction(
        db, _legs(a.id, b.id, 1_000), idempotency_key=key, description="x"
    )
    await db.commit()

    second = await post_transaction(
        db, _legs(a.id, b.id, 1_000), idempotency_key=key, description="x"
    )
    await db.commit()

    assert first.id == second.id
    # The effect only ever happened once, even though post_transaction was
    # called twice with the same key.
    assert await get_balance(db, a.id) == 9_000
    assert await get_balance(db, b.id) == 1_000
