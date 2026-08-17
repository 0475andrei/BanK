import enum
import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Enum as SAEnum
from sqlalchemy.types import Uuid

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin, str_enum_values


class AccountStatus(enum.StrEnum):
    ACTIVE = "active"
    CLOSED = "closed"


class Account(UUIDPKMixin, CreatedAtMixin, Base):
    """No balance column on purpose - balance is always derived as
    SUM(ledger_entries) for this account (see ledger/service.py::get_balance).
    """

    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(
        SAEnum(
            AccountStatus,
            name="account_status",
            native_enum=False,
            length=10,
            values_callable=str_enum_values,
        ),
        nullable=False,
        default=AccountStatus.ACTIVE,
    )
