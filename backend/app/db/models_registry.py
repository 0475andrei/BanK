"""Importing this module populates Base.metadata with every [A]-owned ORM
model, which is what Alembic autogenerate (app/db/migrations/env.py) and
Base.metadata.create_all (tests/conftest.py) rely on.

As [B] adds modules (beneficiaries, payments, cards, pots,
scheduled_transfers, conversations, messages), each new models.py should be
imported here too - otherwise Alembic won't see those tables.
"""

from app.core.audit import AuditLog  # noqa: F401
from app.modules.accounts.models import Account  # noqa: F401
from app.modules.auth.models import UserSession  # noqa: F401
from app.modules.ledger.models import JournalTransaction, LedgerEntry  # noqa: F401
from app.modules.transfers.models import Transfer  # noqa: F401
from app.modules.users.models import User  # noqa: F401
