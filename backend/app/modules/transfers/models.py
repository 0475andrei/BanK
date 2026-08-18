import enum
import uuid

from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum
from sqlalchemy.types import Uuid

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin, str_enum_values


class TransferStatus(enum.StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"


class Transfer(UUIDPKMixin, CreatedAtMixin, Base):
    """A read-friendly, transfers-specific view of one journal. Because
    ledger.post_transaction() is all-or-nothing, a row here only ever gets
    committed once the ledger effect has already succeeded - so in
    practice `status` is always COMPLETED; FAILED exists for schema
    completeness (per flow.md) but nothing in this MVP produces it, since a
    failed attempt simply never gets persisted (the whole request rolls
    back and the client gets an error response instead)."""

    __tablename__ = "transfers"

    journal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("journal_transactions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    to_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[TransferStatus] = mapped_column(
        SAEnum(
            TransferStatus,
            name="transfer_status",
            native_enum=False,
            length=10,
            values_callable=str_enum_values,
        ),
        nullable=False,
        default=TransferStatus.COMPLETED,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
