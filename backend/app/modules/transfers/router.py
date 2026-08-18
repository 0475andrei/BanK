import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.core.idempotency import require_idempotency_key
from app.modules.transfers import service
from app.modules.transfers.models import Transfer
from app.modules.transfers.schemas import TransferCreate, TransferRead
from app.modules.users.models import User

router = APIRouter()


@router.post("", response_model=TransferRead, status_code=201)
async def create_transfer(
    payload: TransferCreate,
    idempotency_key: str = Depends(require_idempotency_key),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Transfer:
    return await service.create_transfer(db, user, payload, idempotency_key)


@router.get("", response_model=list[TransferRead])
async def list_transfers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Transfer]:
    return await service.list_transfers(db, user)


@router.get("/{transfer_id}", response_model=TransferRead)
async def get_transfer(
    transfer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Transfer:
    return await service.get_transfer(db, user, transfer_id)
