import enum
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Enum as SAEnum
from sqlalchemy.types import Uuid

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin, str_enum_values
from app.modules.cards.models import Card


class CardOrderStatus(enum.StrEnum):
    PENDING = "pending"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class CardOrder(UUIDPKMixin, CreatedAtMixin, Base):
    """A request to mail a physical card to the user. Shipping details are
    captured as submitted (not read live off the User row) so a past order
    stays an accurate record even if the user's profile changes later."""

    __tablename__ = "card_orders"

    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("cards.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
        index=True,
    )
    card: Mapped[Card | None] = relationship(
        Card, foreign_keys=[card_id], viewonly=True, lazy="joined"
    )
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[CardOrderStatus] = mapped_column(
        SAEnum(
            CardOrderStatus,
            name="card_order_status",
            native_enum=False,
            length=10,
            values_callable=str_enum_values,
        ),
        nullable=False,
        default=CardOrderStatus.PENDING,
    )
