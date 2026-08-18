from datetime import date

from sqlalchemy import Boolean, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin


class User(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Registration-specific fields (see app/modules/auth/service.py). Nullable
    # at the DB level - not every User row necessarily comes through
    # self-registration (e.g. test fixtures) - but the /auth/register
    # endpoint always requires and validates all of these.
    national_id: Mapped[str | None] = mapped_column(
        String(13), unique=True, nullable=True, index=True
    )
    gender: Mapped[str | None] = mapped_column(String(1), nullable=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
