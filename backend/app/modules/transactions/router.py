import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.modules.transactions import service
from app.modules.transactions.schemas import TransactionEntryRead
from app.modules.users.models import User

router = APIRouter()


@router.get("/{account_id}/transactions", response_model=list[TransactionEntryRead])
async def list_account_transactions(
    account_id: uuid.UUID,
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=service.DEFAULT_LIMIT, ge=1, le=service.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TransactionEntryRead]:
    return await service.list_account_transactions(
        db, user, account_id, date_from=date_from, date_to=date_to, limit=limit, offset=offset
    )
