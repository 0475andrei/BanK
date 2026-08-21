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
from supabase import AsyncClient

from app.ai.context import build_context
from app.ai.providers.base import ModelProvider, ProviderError
from app.ai.schemas import Message
from app.ai.tools.registry import ToolRegistry
from app.core.exceptions import AIProviderError
from app.db.supabase_client import get_supabase
from app.modules.chat.router import get_model_provider
from app.modules.onboarding.agent import OnboardingAgent
from app.modules.onboarding.schemas import OnboardingChatRequest, OnboardingChatResponse
from app.modules.onboarding.tool import CheckExistingAccountTool, ProposeRegistrationTool

router = APIRouter()


def _extract_tool_result(trace: list[Message], tool_name: str) -> dict | None:
    for message in trace:
        if message.role != "tool" or message.name != tool_name:
            continue
        payload = json.loads(message.content or "{}")
        if payload.get("ok"):
            return payload.get("result")
    return None


@router.post("/chat", response_model=OnboardingChatResponse)
async def chat(
    payload: OnboardingChatRequest,
    provider: ModelProvider = Depends(get_model_provider),
    supabase: AsyncClient = Depends(get_supabase),
) -> OnboardingChatResponse:
    # No real identity exists yet - a fresh synthetic id per request is
    # fine since neither tool resolves anything through context (one has
    # no DB access at all, the other only reads users by email/national_id,
    # not by identity).
    context = build_context(user_id=f"onboarding-{uuid.uuid4()}", account_ids=())

    tools = ToolRegistry([ProposeRegistrationTool(), CheckExistingAccountTool(supabase)])
    agent = OnboardingAgent(provider, tools)
    conversation = [*payload.history, Message(role="user", content=payload.message)]

    try:
        reply, trace = await agent.run(conversation, context)
    except ProviderError as exc:
        raise AIProviderError() from exc

    updated_history = [*conversation, *trace, Message(role="assistant", content=reply)]

    account_conflict = _extract_tool_result(trace, CheckExistingAccountTool.name)
    if account_conflict is not None and not account_conflict.get("exists"):
        account_conflict = None

    return OnboardingChatResponse(
        reply=reply,
        history=updated_history,
        collected_fields=_extract_tool_result(trace, ProposeRegistrationTool.name),
        account_conflict=account_conflict,
    )
