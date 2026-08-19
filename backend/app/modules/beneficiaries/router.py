from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.core.dependencies import get_current_user
from app.db.supabase_client import get_supabase
from app.modules.beneficiaries import service
from app.modules.beneficiaries.schemas import BeneficiaryRead
from app.modules.users.schemas import UserRead

router = APIRouter()


@router.get("", response_model=list[BeneficiaryRead])
async def list_beneficiaries(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[dict]:
    return await service.list_beneficiaries(supabase, user)
