from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.ai.schemas import Message

MAX_MESSAGE_CHARS = 4000


class OnboardingChatRequest(BaseModel):
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS),
    ]
    # Pre-auth: there's no user to own server-side history against (unlike
    # /chat's conversations table), so the client holds the transcript and
    # reposts it each turn - same Message shape, just round-tripped instead
    # of stored.
    history: list[Message] = Field(default_factory=list)


class OnboardingChatResponse(BaseModel):
    reply: str
    history: list[Message]
    #: Set once the agent has called propose_registration - the exact
    #: payload the frontend should POST to /auth/register once the user
    #: confirms. None until then.
    collected_fields: dict | None = None
    #: Set once check_existing_account found a match ({exists, matched_field,
    #: email}) - lets the frontend short-circuit straight to the
    #: password-reset offer instead of waiting for a later 409 on submit.
    account_conflict: dict | None = None
