"""Trusted request context — who the AI layer is acting for.

THE RULE: identity enters here, at the edge, from the caller/session. It is
never read from model output. A `Context` is created once per request and
threaded down to the tools; a tool asks the Context which account it may touch,
and the Context is the only thing allowed to answer.

`Context` is frozen: nothing downstream — agent, tool, or model-authored
argument — can widen it mid-loop.

Real auth exists now (`core/dependencies.get_current_user`), so the only thing
that changes per caller is who builds this object: `build_context_for_user` for
a real authenticated request, `dev_context` for the CLI. Agents and tools are
untouched either way — they only ever see a `Context`.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

if TYPE_CHECKING:
    from supabase import AsyncClient

    from app.modules.users.schemas import UserRead


class IdentityError(Exception):
    """Base for identity/authorisation failures inside the AI layer.

    Messages must stay safe to show a model: never echo the identifier that was
    refused, or the refusal itself becomes a disclosure channel.
    """


class AccessDeniedError(IdentityError):
    """The caller asked for a resource the context user does not own."""

    def __init__(self, message: str = "that account is not accessible for this user") -> None:
        super().__init__(message)


class NoAccountAvailableError(IdentityError):
    """The context user has no accounts at all, so nothing can be resolved."""

    def __init__(self, message: str = "this user has no accounts available") -> None:
        super().__init__(message)


class Context(BaseModel):
    """The authenticated caller, as far as the AI layer is concerned.

    `account_ids` is the user's ownership allowlist. Today it is dev-supplied;
    later it comes from the accounts module, scoped by the session user. Either
    way it is the ceiling on what any tool can reach.
    """

    model_config = ConfigDict(frozen=True)

    user_id: str = Field(min_length=1)
    account_ids: tuple[str, ...] = ()

    @field_validator("account_ids", mode="before")
    @classmethod
    def _coerce(cls, value: object) -> object:
        """Accept any sequence; store immutably."""
        if isinstance(value, (list, set, frozenset)):
            return tuple(value)
        return value

    @property
    def default_account_id(self) -> str | None:
        """The account used when the model names none."""
        return self.account_ids[0] if self.account_ids else None

    def owns(self, account_id: str) -> bool:
        return account_id in self.account_ids

    def resolve_account(self, requested: str | None = None) -> str:
        """Decide which account a tool may read.

        `requested` is UNTRUSTED — it comes from the model. It can only ever
        narrow the selection to something already in `account_ids`; it can never
        widen it. Raises instead of falling back, so a refusal is never mistaken
        for a successful read of a different account.
        """
        if requested is None:
            if not self.account_ids:
                raise NoAccountAvailableError()
            return self.account_ids[0]

        if not self.owns(requested):
            # Deliberately does not carry `requested` — see IdentityError.
            raise AccessDeniedError()
        return requested


# ---------------------------------------------------------------------------
# DEV ONLY — the CLI's identity source.
# ---------------------------------------------------------------------------
# The CLI (`python -m app.ai.chat`) has no session cookie to authenticate with,
# so it supplies a fixed identity instead. Real HTTP requests must not use this
# — they go through `build_context_for_user` below, which verifies the accounts
# against the database.
_DEV_USER_ID = "dev-user-0001"
_DEV_ACCOUNT_IDS = ("acc-checking-001", "acc-savings-002")


def dev_context() -> Context:
    """A local identity for the CLI. NOT for production use.

    DEV ONLY. Do not use inside an HTTP request handler. For real requests, use
    `build_context_for_user(user, supabase)`, which derives the account
    allowlist from the database rather than trusting whatever was exported.

    `scripts/seed_dev_user.py` creates a real user + funded account and prints
    their ids; exporting DEV_USER_ID / DEV_ACCOUNT_IDS (comma-separated) makes
    the CLI act as that seeded identity instead of the fixed placeholders.
    This is only a way to *supply* ids - the ids are still not verified against
    the database, so it remains dev-only and is not a substitute for auth.
    """
    user_id = os.environ.get("DEV_USER_ID") or _DEV_USER_ID

    raw_accounts = os.environ.get("DEV_ACCOUNT_IDS")
    if raw_accounts:
        account_ids = tuple(part.strip() for part in raw_accounts.split(",") if part.strip())
    else:
        account_ids = _DEV_ACCOUNT_IDS

    return Context(user_id=user_id, account_ids=account_ids)


def build_context(user_id: str, account_ids: Sequence[str]) -> Context:
    """Explicit construction point for callers that already know the user.

    Takes both values as given. Callers holding an authenticated user but no
    account list should use `build_context_for_user` instead, which looks the
    accounts up rather than trusting a caller-supplied list.
    """
    return Context(user_id=user_id, account_ids=tuple(account_ids))


async def build_context_for_user(user: UserRead, supabase: AsyncClient) -> Context:
    """Build a verified `Context` for an already-authenticated user.

    THE trusted way to build a Context for a real HTTP request. `user` must
    come from `core.dependencies.get_current_user` — i.e. it is the product of
    a valid session cookie, never of anything the client (or the model) sent in
    a request body.

    Identity is taken from `user.id` and the ownership allowlist is derived
    from the database, so `account_ids` reflects what this user actually owns
    at this moment. Nothing here reads client input, and nothing here reads
    model output.

    A user with no accounts is a legitimate state (they just registered), so
    this returns a valid Context with an empty `account_ids` rather than
    raising. Tools that need an account then fail cleanly and specifically via
    `NoAccountAvailableError` when they call `resolve_account`.
    """
    # Imported here, not at module scope, to keep `app.ai` importable without
    # dragging in the banking modules and the Supabase SDK - the agent/tool
    # tests rely on this module staying dependency-light.
    from app.modules.accounts import service as accounts_service

    accounts = await accounts_service.list_accounts(supabase, user)
    return Context(
        user_id=str(user.id),
        account_ids=tuple(str(account["id"]) for account in accounts),
    )
