"""Trusted request context — who the AI layer is acting for.

THE RULE: identity enters here, at the edge, from the caller/session. It is
never read from model output. A `Context` is created once per request and
threaded down to the tools; a tool asks the Context which account it may touch,
and the Context is the only thing allowed to answer.

`Context` is frozen: nothing downstream — agent, tool, or model-authored
argument — can widen it mid-loop.

Person A owns real auth. When `core/dependencies.get_current_user` exists, the
only thing that changes is who builds this object (see `dev_context` below);
agents and tools are untouched.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
# DEV ONLY — delete once real auth exists.
# ---------------------------------------------------------------------------
# There is no auth yet (Person A owns it), so the CLI supplies a fixed identity.
# This is the ONE place that knows where identity comes from. Swapping it for
# the real thing is a one-line change here:
#
#     def build_context(user = Depends(get_current_user)) -> Context:
#         return Context(user_id=str(user.id), account_ids=user.account_ids)
#
# Nothing in agents/ or tools/ changes when that happens.
_DEV_USER_ID = "dev-user-0001"
_DEV_ACCOUNT_IDS = ("acc-checking-001", "acc-savings-002")


def dev_context() -> Context:
    """A local identity for the CLI. NOT for production use.

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

    The future `/chat` endpoint calls this with values from `get_current_user`.
    """
    return Context(user_id=user_id, account_ids=tuple(account_ids))
