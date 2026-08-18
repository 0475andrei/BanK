import enum
import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum
from sqlalchemy.types import Uuid

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin, str_enum_values


class CardStatus(enum.StrEnum):
    ACTIVE = "active"
    FROZEN = "frozen"
    CANCELLED = "cancelled"


class Card(UUIDPKMixin, CreatedAtMixin, Base):
    """Only last4 is persisted - the full number (generated in
    card_numbers.py) is returned once, at issue time, and never stored.
    "Deleting" a card in the API is really cancelling it (status ->
    cancelled) - rows are never hard-deleted, same append-only spirit as
    the rest of the schema."""

    __tablename__ = "cards"

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[CardStatus] = mapped_column(
        SAEnum(
            CardStatus,
            name="card_status",
            native_enum=False,
            length=10,
            values_callable=str_enum_values,
        ),
        nullable=False,
        default=CardStatus.ACTIVE,
    )
    spending_limit_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
