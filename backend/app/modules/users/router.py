from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.modules.users import service
from app.modules.users.models import User
from app.modules.users.schemas import UserRead, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def get_my_profile(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me", response_model=UserRead)
async def update_my_profile(
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> User:
    return await service.update_profile(db, user, payload)
