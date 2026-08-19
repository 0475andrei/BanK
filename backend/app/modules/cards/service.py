import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.core.exceptions import AccountClosedError, NotFoundError
from app.modules.accounts import service as accounts_service
from app.modules.accounts.models import Account, AccountStatus
from app.modules.cards.card_numbers import generate_card_number, generate_cvv, generate_expiry
from app.modules.cards.models import Card, CardStatus
from app.modules.cards.schemas import CardCreate
from app.modules.users.models import User


async def issue_card(db: AsyncSession, user: User, payload: CardCreate) -> Card:
    account = await accounts_service.get_account(db, user, payload.account_id)
    if account.status != AccountStatus.ACTIVE:
        raise AccountClosedError("Cannot issue a card for a closed account.")

    card_number = generate_card_number()
    expiry_month, expiry_year = generate_expiry()
    card = Card(
        account_id=account.id,
        card_number=card_number,
        last4=card_number[-4:],
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        cvv=generate_cvv(),
        status=CardStatus.ACTIVE,
        spending_limit_minor=payload.spending_limit_minor,
    )
    db.add(card)
    await db.flush()

    await record_audit_event(
        db,
        user_id=user.id,
        action="cards.issue",
        entity=f"cards:{card.id}",
        metadata={"account_id": str(account.id)},
    )
    return card


async def list_cards(db: AsyncSession, user: User) -> list[Card]:
    stmt = (
        select(Card)
        .join(Account, Account.id == Card.account_id)
        .where(Account.user_id == user.id)
        .order_by(Card.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def cancel_card(db: AsyncSession, user: User, card_id: uuid.UUID) -> Card:
    stmt = (
        select(Card)
        .join(Account, Account.id == Card.account_id)
        .where(Card.id == card_id, Account.user_id == user.id)
    )
    card = (await db.execute(stmt)).scalar_one_or_none()
    if card is None:
        raise NotFoundError("Card not found.")

    if card.status != CardStatus.CANCELLED:
        card.status = CardStatus.CANCELLED
        await db.flush()
        await record_audit_event(
            db, user_id=user.id, action="cards.cancel", entity=f"cards:{card.id}"
        )

    return card
