"""Shared declarative base + column mixins for every ORM model in the app.

Every module's models.py (owned by whoever owns that module) imports Base
from here. This keeps a single MetaData/registry so Alembic autogenerate can
see every table regardless of which module defines it - see
app/db/migrations/env.py.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid


class Base(DeclarativeBase):
    pass


def str_enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Pass as `values_callable=` to sqlalchemy.Enum for any StrEnum column.

    SQLAlchemy's Enum type stores/validates using the member NAME by
    default (e.g. "ACTIVE"), not its value ("active") - surprising for a
    StrEnum, and it would silently drift from both flow.md's lowercase
    schema and the lowercase values the API already returns (Pydantic
    serializes StrEnum by value). This makes the DB column use the value
    too, so the DB, the API, and the spec all agree.
    """
    return [member.value for member in enum_cls]


class UUIDPKMixin:
    """id = UUID everywhere, per the schema spec."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    """Timestamps are TIMESTAMPTZ, per the schema spec."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
