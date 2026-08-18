"""The auth module is now fully implemented (models, service, router) -
this docstring used to say only the model lived here pending a teammate;
that handoff has happened, see docs/AUTH_HANDOFF.md for how it's wired.

UserSession (not Session) to avoid colliding with sqlalchemy.orm.Session /
AsyncSession in code that imports both.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Base, CreatedAtMixin, UUIDPKMixin
from app.modules.users.models import User


class UserSession(UUIDPKMixin, CreatedAtMixin, Base):
    __tablename__ = "sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped[User] = relationship(lazy="joined")


class LoginAttempt(UUIDPKMixin, CreatedAtMixin, Base):
    """Append-only log of login attempts, used only to rate-limit repeated
    failures per email (see auth/service.py). Deliberately keyed by the
    submitted email string, not a user_id FK - an attempt against an
    unknown email is itself something we want to be able to rate-limit."""

    __tablename__ = "login_attempts"

    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
