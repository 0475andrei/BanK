from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.ai.schemas import Message

#: Roughly a long paragraph. Bounds the prompt the model is asked to process.
MAX_MESSAGE_CHARS = 4000

#: Conversation history is client-supplied (nothing is persisted yet), so it
#: needs a ceiling of its own - otherwise one request could hand the model an
#: unbounded transcript.
MAX_HISTORY_MESSAGES = 50


class ClientMessage(Message):
    """A conversation turn a *client* is allowed to replay back to us.

    Narrows `Message.role` to the two dialogue roles. `system` is excluded on
    purpose: the agent supplies its own system prompt, and letting a caller add
    another would be a prompt-injection seam. `tool` is excluded because tool
    results are produced server-side by the tool loop - a client-authored one
    would be fabricated data handed to the model as if it were real.

    Narrowing the type (rather than validating in a `field_validator`) keeps the
    rejection a plain Pydantic literal error, which the app's 422 handler can
    serialise as-is.
    """

    role: Literal["user", "assistant"]


class ChatRequest(BaseModel):
    # `strip_whitespace` before `min_length` so a whitespace-only message is a
    # 422 like an empty one, rather than an empty prompt reaching the model.
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS),
    ]
    history: list[ClientMessage] = Field(
        default_factory=list, max_length=MAX_HISTORY_MESSAGES
    )


class ChatResponse(BaseModel):
    reply: str
    #: The conversation so far, for the client to send back on the next turn.
    #: Server-side persistence lands later; until then the client is the only
    #: thing holding the thread together.
    history: list[Message]
