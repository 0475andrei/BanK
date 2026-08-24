"""/chat - the AI layer's HTTP surface.

Identity is established here, at the edge: the session cookie resolves to a
`UserRead` via `get_current_user`, and `build_context_for_user` turns that into
the trusted `Context` every tool resolves accounts against. Nothing the client
sends contributes to identity.

The server owns conversation history (see `conversations_service`): the client
only ever holds a `conversation_id`, so the transcript survives a page reload.
"""

import uuid

from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.ai.context import build_context_for_user
from app.ai.providers.base import ModelProvider, ProviderError
from app.ai.providers.embedding_base import EmbeddingProvider
from app.ai.providers.mock_embedding_provider import MockEmbeddingProvider
from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas import Message, ModelResponse
from app.ai.service import AIService
from app.config import ConfigurationError, Settings, get_settings
from app.core.dependencies import get_current_user
from app.core.exceptions import (
    AIProviderError,
    AIProviderMisconfiguredError,
    AIServiceUnavailableError,
)
from app.db.supabase_client import get_supabase
from app.modules.chat import conversations_service
from app.modules.chat.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationRead,
    ConversationRenameRequest,
)
from app.modules.users.schemas import UserRead

router = APIRouter()

PROVIDER_MOCK = "mock"
PROVIDER_AZURE = "azure"
_VALID_PROVIDERS = (PROVIDER_MOCK, PROVIDER_AZURE)

MOCK_REPLY = (
    "AI provider is set to mock — set AI_PROVIDER=azure in .env to use the real model."
)


def get_model_provider(settings: Settings = Depends(get_settings)) -> ModelProvider:
    """Pick the provider from configuration.

    A FastAPI dependency rather than a plain call so tests can override it with
    a scripted `MockProvider`, the same way they override `get_supabase`.
    """
    choice = settings.AI_PROVIDER.strip().lower()

    if choice == PROVIDER_MOCK:
        # `repeat_last` so a multi-turn conversation doesn't exhaust the script.
        return MockProvider([ModelResponse(text=MOCK_REPLY)], repeat_last=True)

    if choice == PROVIDER_AZURE:
        from app.ai.providers.azure_provider import AzureOpenAIProvider

        try:
            return AzureOpenAIProvider(settings)
        except ConfigurationError as exc:
            # The operator sees the specifics in the logs; the caller does not.
            raise AIServiceUnavailableError() from exc

    raise AIProviderMisconfiguredError(
        f"AI_PROVIDER={settings.AI_PROVIDER!r} is not a known provider. "
        f"Valid values: {', '.join(_VALID_PROVIDERS)}."
    )


def get_embedding_provider(settings: Settings = Depends(get_settings)) -> EmbeddingProvider:
    """Same provider-selection contract as `get_model_provider`, for embeddings.

    Kept as a separate dependency (not folded into `get_model_provider`)
    because a deployment can have chat configured without embeddings - only
    the docs agent's tool actually calls this one, so only asking for
    documentation should be able to fail on it.
    """
    choice = settings.AI_PROVIDER.strip().lower()

    if choice == PROVIDER_MOCK:
        return MockEmbeddingProvider()

    if choice == PROVIDER_AZURE:
        from app.ai.providers.azure_embedding_provider import AzureEmbeddingProvider

        try:
            return AzureEmbeddingProvider(settings)
        except ConfigurationError as exc:
            raise AIServiceUnavailableError() from exc

    raise AIProviderMisconfiguredError(
        f"AI_PROVIDER={settings.AI_PROVIDER!r} is not a known provider. "
        f"Valid values: {', '.join(_VALID_PROVIDERS)}."
    )


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
    provider: ModelProvider = Depends(get_model_provider),
    embedding_provider: EmbeddingProvider = Depends(get_embedding_provider),
) -> ChatResponse:
    # THE EDGE. Built from the authenticated session, never from the payload.
    context = await build_context_for_user(user, supabase)

    if payload.conversation_id is None:
        conversation = await conversations_service.create_conversation(supabase, user)
    else:
        # Ownership-checked: raises ConversationNotFoundError for a foreign or
        # nonexistent id, never leaking which one it was.
        conversation = await conversations_service.get_conversation(
            supabase, user, payload.conversation_id
        )
    conversation_id = uuid.UUID(conversation["id"])

    history = await conversations_service.load_messages(supabase, conversation_id)

    service = AIService(supabase, provider=provider, embedding_provider=embedding_provider)
    try:
        reply, updated_history, routing = await service.handle_message(
            history, payload.message, context
        )
    except ProviderError as exc:
        raise AIProviderError() from exc

    # handle_message returns `history` unchanged plus every new turn (the user
    # message, any tool-call/tool-result trace, the final reply) appended in
    # order - everything already in `history` is already stored.
    new_messages = updated_history[len(history) :]
    for message in new_messages:
        # The routing decision describes the turn the agent produced, so it is
        # attached to that final assistant message and to nothing else.
        is_final_reply = message is new_messages[-1]
        await conversations_service.append_message(
            supabase,
            conversation_id,
            message,
            routing=routing if is_final_reply else None,
        )

    return ChatResponse(reply=reply, conversation_id=conversation_id, routing=routing)


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[ConversationRead]:
    return await conversations_service.list_conversations(supabase, user)


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> dict:
    await conversations_service.get_conversation(supabase, user, conversation_id)
    await conversations_service.delete_conversation(supabase, conversation_id)
    return {"status": "ok"}


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationRenameRequest,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> dict:
    await conversations_service.get_conversation(supabase, user, conversation_id)
    await conversations_service.rename_conversation(supabase, conversation_id, payload.title)
    return {"status": "ok"}


@router.get("/conversations/{conversation_id}/messages", response_model=list[Message])
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> list[Message]:
    await conversations_service.get_conversation(supabase, user, conversation_id)
    return await conversations_service.load_messages(supabase, conversation_id)


@router.patch("/conversations/{conversation_id}", response_model=ConversationRead)
async def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationRenameRequest,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> dict:
    return await conversations_service.rename_conversation(
        supabase, user, conversation_id, payload.title
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
) -> None:
    await conversations_service.delete_conversation(supabase, user, conversation_id)
