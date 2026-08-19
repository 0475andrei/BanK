"""Password hashing + server-side session token primitives.

These are the shared building blocks. This file does NOT expose any HTTP
endpoints — the [A]-owned core/dependencies.py::get_current_user is the
*consumer* of sessions created with these helpers, and the auth teammate's
login/logout/register endpoints are the *producer*. See
docs/AUTH_HANDOFF.md for the exact contract.

Session design: the cookie carries a single opaque, high-entropy random
token (generate_session_token). We never store that raw token — only its
SHA-256 hash (hash_session_token) goes in sessions.token_hash. This is the
same "store a hash, not the secret" pattern as passwords, but SHA-256 (not
bcrypt) is appropriate here because the token itself already has 256 bits of
entropy, so there's nothing for a slow KDF to protect against.
"""

import hashlib
import secrets

import bcrypt

SESSION_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # Malformed/foreign hash format - never let this crash the request.
        return False


def generate_session_token() -> str:
    """Raw token to put in the cookie. Returned to the client exactly once
    (at login time) - it is never persisted, only its hash is."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Deterministic hash used both to store and to look up sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
