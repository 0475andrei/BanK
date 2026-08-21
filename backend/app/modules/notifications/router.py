from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.db.supabase_client import get_supabase
from app.modules.notifications import service
from app.modules.notifications.schemas import NotificationRead, UnreadCountRead
from app.modules.users.schemas import UserRead

router = APIRouter()


@router.get("", response_model=list[NotificationRead])
async def list_my_notifications(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[NotificationRead]:
    return await service.list_notifications(supabase, user)


@router.get("/unread-count", response_model=UnreadCountRead)
async def get_unread_count(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> UnreadCountRead:
    count = await service.count_unread(supabase, user)
    return UnreadCountRead(count=count)


@router.post("/mark-read", status_code=204)
async def mark_read(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> None:
    await service.mark_all_read(supabase, user)
