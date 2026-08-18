import enum
import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum
from sqlalchemy.types import Uuid

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin, str_enum_values


class LedgerDirection(enum.StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalTransaction(UUIDPKMixin, CreatedAtMixin, Base):
    """Groups the legs of ONE money movement. idempotency_key is the
    dedupe boundary the whole ledger relies on - see
    modules/ledger/service.py::post_transaction."""

    __tablename__ = "journal_transactions"

    reference: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)


class LedgerEntry(UUIDPKMixin, CreatedAtMixin, Base):
    """IMMUTABLE, append-only. A row is never updated or deleted; a
    correction is a new reversing entry. An account's balance is always
    SUM(ledger_entries) for that account - there is no stored balance
    anywhere."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_ledger_entries_amount_positive"),
    )

    journal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("journal_transactions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    direction: Mapped[LedgerDirection] = mapped_column(
        SAEnum(
            LedgerDirection,
            name="ledger_direction",
            native_enum=False,
            length=10,
            values_callable=str_enum_values,
        ),
        nullable=False,
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
