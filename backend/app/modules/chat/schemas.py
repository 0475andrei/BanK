import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

#: Roughly a long paragraph. Bounds the prompt the model is asked to process.
MAX_MESSAGE_CHARS = 4000


class ChatRequest(BaseModel):
    # `strip_whitespace` before `min_length` so a whitespace-only message is a
    # 422 like an empty one, rather than an empty prompt reaching the model.
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_MESSAGE_CHARS),
    ]
    #: Null starts a new conversation. Otherwise the caller is continuing one
    #: it was handed by an earlier response - ownership is checked server-side.
    conversation_id: uuid.UUID | None = None


class ChatResponse(BaseModel):
    reply: str
    #: Always returned, so the client knows what to send on the next turn -
    #: history itself now lives server-side (see conversations_service).
    conversation_id: uuid.UUID


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
