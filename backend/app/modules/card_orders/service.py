from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit_event
from app.modules.accounts import service as accounts_service
from app.modules.accounts.models import Account
from app.modules.card_orders.models import CardOrder
from app.modules.card_orders.schemas import CardOrderCreate
from app.modules.cards import service as cards_service
from app.modules.cards.schemas import CardCreate
from app.modules.users.models import User


async def create_order(db: AsyncSession, user: User, payload: CardOrderCreate) -> CardOrder:
    account = await accounts_service.get_account(db, user, payload.account_id)

    card = await cards_service.issue_card(db, user, CardCreate(account_id=account.id))

    order = CardOrder(
        account_id=account.id,
        card_id=card.id,
        full_name=payload.full_name,
        phone=payload.phone,
        address=payload.address,
        city=payload.city,
        postal_code=payload.postal_code,
        country=payload.country,
    )
    db.add(order)
    await db.flush()
    order.card = card

    await record_audit_event(
        db,
        user_id=user.id,
        action="card_orders.create",
        entity=f"card_orders:{order.id}",
        metadata={"account_id": str(account.id)},
    )
    return order


async def list_orders(db: AsyncSession, user: User) -> list[CardOrder]:
    stmt = (
        select(CardOrder)
        .join(Account, Account.id == CardOrder.account_id)
        .where(Account.user_id == user.id)
        .order_by(CardOrder.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())
