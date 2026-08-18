from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_current_user, get_db
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.users.models import User
from app.modules.users.schemas import UserRead

router = APIRouter()


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.SESSION_TTL_SECONDS,
    )


@router.post("/register", response_model=UserRead, status_code=201)
async def register(
    payload: RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    user, token = await service.register_user(db, payload)
    _set_session_cookie(response, token)
    return user


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    user, token = await service.login_user(db, payload)
    _set_session_cookie(response, token)
    return user


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    await service.logout_user(db, user, token)
    response.delete_cookie(settings.SESSION_COOKIE_NAME)
