"""DIY face login ("varianta DIY cu camera" - see the design discussion this
followed, not WebAuthn/passkeys). Enrollment stores one face_recognition
(dlib) embedding per user; login extracts a fresh embedding from a live
photo and compares it 1:1 against the enrolled one for the claimed email.

IMPORTANT - this is demo-grade biometric auth, not a real security boundary:
there is no liveness detection, so a printed photo or a photo of a photo of
the enrolled user passes it. Good enough for a hackathon-style feature;
never treat this as equivalent to the password/OTP flows for anything that
actually matters. See migration 0011's header for the same caveat.
"""

import hashlib
import secrets
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import face_recognition
import numpy as np
from postgrest.exceptions import APIError
from supabase import AsyncClient

from app.core.audit import record_audit_event
from app.core.exceptions import (
    FaceConfirmationRequiredError,
    InvalidFaceConfirmationError,
    LoginRateLimitedError,
    UnauthorizedError,
    ValidationError,
)
from app.modules.auth import service as auth_service
from app.modules.users.schemas import UserRead

MATCH_THRESHOLD = 0.6
UNIQUE_VIOLATION = "23505"

# Step-up auth for large transfers/payments (see enforce_face_confirmation
# below, called from transfers/service.py and payments/service.py). Applied
# regardless of currency - a simplification, not "500000 of any currency"
# being treated as equally large, but good enough for a demo-grade check.
FACE_CONFIRMATION_THRESHOLD_MINOR = 500_000
FACE_CONFIRMATION_TOKEN_TTL_MINUTES = 3


def _extract_embedding(image_bytes: bytes) -> list[float]:
    """Runs fully offline (dlib, in-container) - no photo ever leaves this
    machine, same principle as id_ocr's ID-card extraction."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = Path(tmp.name)

    try:
        image = face_recognition.load_image_file(str(tmp_path))
        encodings = face_recognition.face_encodings(image)
    finally:
        tmp_path.unlink(missing_ok=True)

    if not encodings:
        raise ValidationError("No face detected in the photo. Try a clearer, well-lit picture.")
    if len(encodings) > 1:
        raise ValidationError("Multiple faces detected - only one person can enroll at a time.")
    return encodings[0].tolist()


async def enroll_face(supabase: AsyncClient, user: UserRead, image_bytes: bytes) -> None:
    embedding = _extract_embedding(image_bytes)

    try:
        await (
            supabase.table("face_credentials")
            .insert({"user_id": str(user.id), "embedding": embedding})
            .execute()
        )
    except APIError as exc:
        if exc.code != UNIQUE_VIOLATION:
            raise
        # Already enrolled - re-enrolling replaces the old face, it doesn't
        # stack multiple faces per user.
        await (
            supabase.table("face_credentials")
            .update({"embedding": embedding})
            .eq("user_id", str(user.id))
            .execute()
        )

    await record_audit_event(
        supabase, user_id=user.id, action="auth.face_enroll", entity=f"users:{user.id}"
    )


async def remove_face(supabase: AsyncClient, user: UserRead) -> None:
    await supabase.table("face_credentials").delete().eq("user_id", str(user.id)).execute()
    await record_audit_event(
        supabase, user_id=user.id, action="auth.face_remove", entity=f"users:{user.id}"
    )


async def has_face_enrolled(supabase: AsyncClient, user: UserRead) -> bool:
    resp = (
        await supabase.table("face_credentials")
        .select("id")
        .eq("user_id", str(user.id))
        .maybe_single()
        .execute()
    )
    return resp is not None and resp.data is not None


async def _count_recent_failed_attempts(supabase: AsyncClient, email: str) -> int:
    # Shares login_attempts and the lockout window/threshold with password
    # login (auth/service.py) - too many failed attempts of EITHER kind
    # locks the account the same way.
    window_start = datetime.now(UTC) - timedelta(minutes=auth_service.LOGIN_LOCKOUT_WINDOW_MINUTES)
    resp = (
        await supabase.table("login_attempts")
        .select("id", count="exact")
        .eq("email", email)
        .eq("success", False)
        .gte("created_at", window_start.isoformat())
        .execute()
    )
    return resp.count or 0


async def login_with_face(supabase: AsyncClient, email: str, image_bytes: bytes) -> tuple[UserRead, str]:
    email = email.lower()

    if await _count_recent_failed_attempts(supabase, email) >= auth_service.LOGIN_MAX_FAILED_ATTEMPTS:
        raise LoginRateLimitedError()

    resp = await supabase.table("users").select("*").eq("email", email).maybe_single().execute()
    user_row = resp.data if resp is not None else None

    credential_row = None
    if user_row is not None:
        cred_resp = (
            await supabase.table("face_credentials")
            .select("embedding")
            .eq("user_id", user_row["id"])
            .maybe_single()
            .execute()
        )
        credential_row = cred_resp.data if cred_resp is not None else None

    matched = False
    if user_row is not None and credential_row is not None:
        candidate = _extract_embedding(image_bytes)
        known = np.array(credential_row["embedding"])
        distance = face_recognition.face_distance([known], np.array(candidate))[0]
        matched = bool(distance <= MATCH_THRESHOLD)

    # Same shape as password login: unknown email, no face enrolled, and a
    # non-matching face all fail identically - don't leak which one it was.
    if not matched:
        await supabase.table("login_attempts").insert({"email": email, "success": False}).execute()
        raise UnauthorizedError("Face not recognized.")

    user = UserRead.model_validate(user_row)

    await supabase.table("login_attempts").insert({"email": email, "success": True}).execute()
    await record_audit_event(
        supabase, user_id=user.id, action="auth.face_login", entity=f"users:{user.id}"
    )

    token = await auth_service.start_session(supabase, user)
    return user, token


def _hash_confirmation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_face_confirmation(supabase: AsyncClient, user: UserRead, image_bytes: bytes) -> str:
    """Re-verifies the already-logged-in `user`'s face (1:1, same comparison
    as login_with_face) and issues a short-lived, single-use token proving
    "yes, still you" - the step-up auth transfers/payments require above
    FACE_CONFIRMATION_THRESHOLD_MINOR. Unlike login, identity here comes from
    the session, not the photo - a mismatched face is a straight rejection,
    never "try another email"."""
    cred_resp = (
        await supabase.table("face_credentials")
        .select("embedding")
        .eq("user_id", str(user.id))
        .maybe_single()
        .execute()
    )
    credential_row = cred_resp.data if cred_resp is not None else None
    if credential_row is None:
        raise ValidationError("Face Login is not enabled on this account.")

    candidate = _extract_embedding(image_bytes)
    known = np.array(credential_row["embedding"])
    distance = face_recognition.face_distance([known], np.array(candidate))[0]
    if distance > MATCH_THRESHOLD:
        raise UnauthorizedError("Face not recognized.")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(minutes=FACE_CONFIRMATION_TOKEN_TTL_MINUTES)
    await supabase.table("face_confirmations").insert(
        {
            "user_id": str(user.id),
            "token_hash": _hash_confirmation_token(token),
            "expires_at": expires_at.isoformat(),
        }
    ).execute()
    return token


async def _consume_face_confirmation(supabase: AsyncClient, user: UserRead, token: str) -> None:
    resp = (
        await supabase.table("face_confirmations")
        .select("*")
        .eq("token_hash", _hash_confirmation_token(token))
        .eq("user_id", str(user.id))
        .is_("consumed_at", "null")
        .maybe_single()
        .execute()
    )
    row = resp.data if resp is not None else None
    if row is None:
        raise InvalidFaceConfirmationError()

    expires_at = datetime.fromisoformat(row["expires_at"])
    if datetime.now(UTC) >= expires_at:
        raise InvalidFaceConfirmationError()

    await (
        supabase.table("face_confirmations")
        .update({"consumed_at": datetime.now(UTC).isoformat()})
        .eq("id", row["id"])
        .execute()
    )


def requires_face_confirmation(amount_minor: int) -> bool:
    return amount_minor >= FACE_CONFIRMATION_THRESHOLD_MINOR


async def enforce_face_confirmation(
    supabase: AsyncClient, user: UserRead, amount_minor: int, token: str | None
) -> None:
    """Single call site transfers/service.py and payments/service.py use
    before executing a money movement. No-ops below the threshold, and also
    no-ops (can't require what was never set up) when the user has no face
    enrolled - otherwise raises FaceConfirmationRequiredError when no token
    was supplied, or InvalidFaceConfirmationError when the supplied one
    doesn't check out."""
    if not requires_face_confirmation(amount_minor):
        return
    if not await has_face_enrolled(supabase, user):
        return

    if token is None:
        raise FaceConfirmationRequiredError()
    await _consume_face_confirmation(supabase, user, token)
