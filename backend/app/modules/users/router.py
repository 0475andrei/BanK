from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.db.supabase_client import get_supabase
from app.modules.users import service
from app.modules.users.schemas import UserRead, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserRead)
async def get_my_profile(user: UserRead = Depends(get_current_user)) -> UserRead:
    return user


@router.patch("/me", response_model=UserRead)
async def update_my_profile(
    payload: UserUpdate,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> UserRead:
    return await service.update_profile(supabase, user, payload)
