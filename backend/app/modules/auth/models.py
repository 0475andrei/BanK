"""Only the ORM model lives here. The login/logout/register endpoints
(router.py, service.py, schemas.py) are owned by the teammate building auth
- see docs/AUTH_HANDOFF.md. This model exists in [A]'s scope because
core/dependencies.py::get_current_user (the CONTRACT every protected
endpoint depends on) has to query it.

Named UserSession (not Session) to avoid colliding with
sqlalchemy.orm.Session / AsyncSession in code that imports both.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
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
