"""Response shapes for the admin panel.

Every model here is an EXPLICIT projection, never a `**row` splat. The admin
service reads whole rows from tables that also hold `password_hash`, card
PAN/CVV/expiry and face embeddings; these schemas are the line those must
never cross. Same reasoning as the SECURITY INVARIANT on
app/ai/tools/banking/list_cards.py, and the same rule applies when adding a
field here later.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.card_orders.models import CardOrderStatus

#: Bounds every listing endpoint. Stops an admin (or a bug) from asking for
#: the entire table in one request.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class AdminUserSummary(BaseModel):
    """One row of the users list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: str
    email_verified: bool
    created_at: datetime
    #: Not-null means the account is blocked; the value is when it happened.
    blocked_at: datetime | None = None


class AdminAccountSummary(BaseModel):
    id: uuid.UUID
    name: str
    currency: str
    status: str
    iban: str | None = None
    #: Derived (SUM of ledger entries), never a stored column.
    balance_minor: int


class AdminCardSummary(BaseModel):
    """Card fields safe to show. NEVER card_number, cvv, expiry_month/year -
    those columns exist on the row this is built from."""

    id: uuid.UUID
    account_id: uuid.UUID
    last4: str | None = None
    status: str
    spending_limit_minor: int | None = None


class AdminUserDetail(AdminUserSummary):
    """The users list row, plus what that user holds."""

    phone: str | None = None
    address: str | None = None
    national_id: str | None = None
    accounts: list[AdminAccountSummary] = Field(default_factory=list)
    cards: list[AdminCardSummary] = Field(default_factory=list)


class AdminCardOrderRead(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    card_id: uuid.UUID | None = None
    status: CardOrderStatus
    full_name: str
    phone: str
    address: str
    city: str
    postal_code: str
    country: str
    created_at: datetime
    #: Who the order belongs to - resolved through the account, since
    #: card_orders has no user_id of its own.
    user_id: uuid.UUID | None = None
    user_email: str | None = None


class CardOrderStatusUpdate(BaseModel):
    """The one write the admin panel allows.

    `pending` is absent on purpose: an order moves forward or is cancelled,
    it is never put back into the state it was created in.
    """

    status: Literal["shipped", "delivered", "cancelled"]


class AuditLogEntry(BaseModel):
    id: uuid.UUID
    created_at: datetime
    user_id: uuid.UUID | None = None
    action: str
    entity: str
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class CurrencyTotal(BaseModel):
    currency: str
    account_count: int
    total_minor: int


class AdminStats(BaseModel):
    total_users: int
    total_accounts: int
    total_cards: int
    pending_card_orders: int
    #: One entry per currency in use - the app has no single "total money"
    #: figure because it never converts between currencies.
    totals_by_currency: list[CurrencyTotal] = Field(default_factory=list)


class UserRoleUpdate(BaseModel):
    """Body of PATCH /admin/users/{id}/role.

    Note this is a real HTTP path to granting admin, which
    migrations/0016_admin_role.sql originally ruled out. The trade-offs that
    keep it safe live in service.py::set_user_role: an admin cannot change
    their OWN role, and every change is written to the audit log.
    """

    role: Literal["customer", "admin"]


class UserBlockUpdate(BaseModel):
    """Body of PATCH /admin/users/{id}/blocked."""

    blocked: bool


class AdminTransaction(BaseModel):
    """One ledger entry, with the card it was made on (when one was recorded).

    `card_id` is NULL for everything that does not involve a card - transfers
    between own accounts, incoming payments, and every row written before
    migration 0017. That is a real state, not missing data.
    """

    id: uuid.UUID
    created_at: datetime
    account_id: uuid.UUID
    account_name: str | None = None
    direction: str
    amount_minor: int
    currency: str
    description: str | None = None
    reference: str | None = None
    card_id: uuid.UUID | None = None
    card_last4: str | None = None


class AdminIdentity(BaseModel):
    """What GET /admin/me answers. The frontend calls it to decide whether to
    show the admin link at all - a 403 means "not an admin", which is the
    whole answer it needs."""

    id: uuid.UUID
    email: str
    role: str
