import uuid

from supabase import AsyncClient

from app.ai.schemas import Message, ToolCall
from app.core.exceptions import ConversationNotFoundError
from app.modules.users.schemas import UserRead


async def create_conversation(supabase: AsyncClient, user: UserRead) -> dict:
    resp = (
        await supabase.table("conversations")
        .insert({"user_id": str(user.id)})
        .execute()
    )
    return resp.data[0]


async def get_conversation(
    supabase: AsyncClient, user: UserRead, conversation_id: uuid.UUID
) -> dict:
    """Ownership-checked conversation read. Same shape as accounts.get_account_for_owner:
    a missing id and one owned by someone else look identical to the caller."""
    resp = (
        await supabase.table("conversations")
        .select("*")
        .eq("id", str(conversation_id))
        .eq("user_id", str(user.id))
        .maybe_single()
        .execute()
    )
    conversation = resp.data if resp is not None else None
    if conversation is None:
        raise ConversationNotFoundError()
    return conversation


async def list_conversations(supabase: AsyncClient, user: UserRead) -> list[dict]:
    resp = (
        await supabase.table("conversations")
        .select("*")
        .eq("user_id", str(user.id))
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data


async def append_message(
    supabase: AsyncClient, conversation_id: uuid.UUID, message: Message
) -> dict:
    resp = (
        await supabase.table("messages")
        .insert(
            {
                "conversation_id": str(conversation_id),
                "role": message.role,
                "content": message.content,
                "tool_calls": [tc.model_dump() for tc in message.tool_calls] or None,
                "tool_call_id": message.tool_call_id,
                "name": message.name,
            }
        )
        .execute()
    )
    return resp.data[0]


async def load_messages(supabase: AsyncClient, conversation_id: uuid.UUID) -> list[Message]:
    resp = (
        await supabase.table("messages")
        .select("*")
        .eq("conversation_id", str(conversation_id))
        .order("created_at")
        .execute()
    )
    return [
        Message(
            role=row["role"],
            content=row["content"],
            tool_calls=[ToolCall(**tc) for tc in (row["tool_calls"] or [])],
            tool_call_id=row["tool_call_id"],
            name=row["name"],
        )
        for row in resp.data
    ]
