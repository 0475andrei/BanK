"""POST /chat - the AI layer's only HTTP surface.

Identity is established here, at the edge: the session cookie resolves to a
`UserRead` via `get_current_user`, and `build_context_for_user` turns that into
the trusted `Context` every tool resolves accounts against. Nothing the client
sends contributes to identity.

No persistence yet - `history` round-trips through the client, and the server
keeps nothing between requests.
"""

from fastapi import APIRouter, Depends
from supabase import AsyncClient

from app.ai.context import build_context_for_user
from app.ai.providers.base import ModelProvider, ProviderError
from app.ai.providers.mock_provider import MockProvider
from app.ai.schemas import ModelResponse
from app.ai.service import AIService
from app.config import ConfigurationError, Settings, get_settings
from app.core.dependencies import get_current_user
from app.core.exceptions import (
    AIProviderError,
    AIProviderMisconfiguredError,
    AIServiceUnavailableError,
)
from app.db.supabase_client import get_supabase
from app.modules.chat.schemas import ChatRequest, ChatResponse
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


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    supabase: AsyncClient = Depends(get_supabase),
    user: UserRead = Depends(get_current_user),
    provider: ModelProvider = Depends(get_model_provider),
) -> ChatResponse:
    # THE EDGE. Built from the authenticated session, never from the payload.
    context = await build_context_for_user(user, supabase)

    service = AIService(supabase, provider=provider)

    try:
        reply, history = await service.handle_message(
            payload.history, payload.message, context
        )
    except ProviderError as exc:
        raise AIProviderError() from exc

    return ChatResponse(reply=reply, history=history)
