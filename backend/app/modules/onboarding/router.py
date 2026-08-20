"""POST /onboarding/chat - Comodul, the pre-auth registration assistant.

No session required: this runs before an account exists. History is
client-held (see OnboardingChatRequest) rather than server-stored, since
there's no authenticated user to own a conversations row yet - see
app/modules/chat/router.py for the authenticated equivalent this mirrors.
The actual account only ever gets created by the frontend POSTing to
/auth/register once the user explicitly confirms - this endpoint only ever
proposes, never submits.
"""

import json
import uuid

from fastapi import APIRouter, Depends

from app.ai.context import build_context
from app.ai.providers.base import ModelProvider, ProviderError
from app.ai.schemas import Message
from app.ai.tools.registry import ToolRegistry
from app.core.exceptions import AIProviderError
from app.modules.chat.router import get_model_provider
from app.modules.onboarding.agent import OnboardingAgent
from app.modules.onboarding.schemas import OnboardingChatRequest, OnboardingChatResponse
from app.modules.onboarding.tool import ProposeRegistrationTool

router = APIRouter()


def _extract_collected_fields(trace: list[Message]) -> dict | None:
    for message in trace:
        if message.role != "tool" or message.name != ProposeRegistrationTool.name:
            continue
        payload = json.loads(message.content or "{}")
        if payload.get("ok"):
            return payload.get("result")
    return None


@router.post("/chat", response_model=OnboardingChatResponse)
async def chat(
    payload: OnboardingChatRequest,
    provider: ModelProvider = Depends(get_model_provider),
) -> OnboardingChatResponse:
    # No real identity exists yet - a fresh synthetic id per request is
    # fine since propose_registration ignores context entirely (it has no
    # DB access and resolves nothing through it).
    context = build_context(user_id=f"onboarding-{uuid.uuid4()}", account_ids=())

    agent = OnboardingAgent(provider, ToolRegistry([ProposeRegistrationTool()]))
    conversation = [*payload.history, Message(role="user", content=payload.message)]

    try:
        reply, trace = await agent.run(conversation, context)
    except ProviderError as exc:
        raise AIProviderError() from exc

    updated_history = [*conversation, *trace, Message(role="assistant", content=reply)]

    return OnboardingChatResponse(
        reply=reply,
        history=updated_history,
        collected_fields=_extract_collected_fields(trace),
    )
