from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile
from supabase import AsyncClient

from app.config import settings
from app.core.dependencies import get_current_user
from app.core.exceptions import ValidationError
from app.db.supabase_client import get_supabase
from app.modules.face_auth import service
from app.modules.face_auth.schemas import FaceConfirmationRead, FaceStatusRead
from app.modules.users.schemas import UserRead

router = APIRouter()

_MAX_UPLOAD_BYTES = 8 * 1024 * 1024

FACE_CONFIRMATION_HEADER_NAME = "X-Face-Confirmation"


async def optional_face_confirmation_token(
    token: str | None = Header(default=None, alias=FACE_CONFIRMATION_HEADER_NAME),
) -> str | None:
    """FastAPI dependency for transfers/payments routers: use as
    `face_token: str | None = Depends(optional_face_confirmation_token)`
    on any endpoint that calls face_auth.service.enforce_face_confirmation."""
    return token


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        max_age=settings.SESSION_TTL_SECONDS,
    )


async def _read_image(file: UploadFile) -> bytes:
    if file.content_type not in {"image/jpeg", "image/png"}:
        raise ValidationError("Only JPEG or PNG images are supported.")
    contents = await file.read()
    if not contents:
        raise ValidationError("Uploaded file is empty.")
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise ValidationError("Image is too large (max 8 MB).")
    return contents


@router.get("/status", response_model=FaceStatusRead)
async def get_face_status(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> FaceStatusRead:
    enrolled = await service.has_face_enrolled(supabase, user)
    return FaceStatusRead(enrolled=enrolled)


@router.post("/enroll", status_code=204)
async def enroll(
    file: UploadFile = File(...),
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> None:
    image_bytes = await _read_image(file)
    await service.enroll_face(supabase, user, image_bytes)


@router.delete("/enroll", status_code=204)
async def unenroll(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> None:
    await service.remove_face(supabase, user)


@router.post("/confirm", response_model=FaceConfirmationRead)
async def confirm(
    file: UploadFile = File(...),
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> FaceConfirmationRead:
    image_bytes = await _read_image(file)
    token = await service.create_face_confirmation(supabase, user, image_bytes)
    return FaceConfirmationRead(token=token)


@router.post("/login", response_model=UserRead)
async def login_with_face(
    response: Response,
    email: str = Form(...),
    file: UploadFile = File(...),
    supabase: AsyncClient = Depends(get_supabase),
) -> UserRead:
    image_bytes = await _read_image(file)
    user, token = await service.login_with_face(supabase, email, image_bytes)
    _set_session_cookie(response, token)
    return user
