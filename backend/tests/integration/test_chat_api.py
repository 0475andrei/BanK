"""POST /api/v1/chat - the AI layer over HTTP.

The model is always a scripted `MockProvider`, injected by overriding the
`get_model_provider` dependency (the same seam `get_supabase` uses), so nothing
here needs Azure credentials or touches the network. History now lives
server-side (conversations/messages tables); the client only holds a
conversation_id, so these tests assert on that plus what got persisted.
"""

import json
import uuid

import pytest

from app.ai.schemas import ModelResponse, ToolCall
from app.modules.accounts.service import OPENING_BALANCE_MINOR
from app.modules.chat.schemas import MAX_MESSAGE_CHARS


async def test_chat_requires_authentication(client):
    resp = await client.post("/api/v1/chat", json={"message": "hello"})

    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


async def test_chat_returns_reply_and_a_conversation_id(authed_client, scripted_provider):
    client, _user = authed_client
    scripted_provider(ModelResponse(text="Hello! How can I help with your banking?"))

    resp = await client.post("/api/v1/chat", json={"message": "hello"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == "Hello! How can I help with your banking?"
    assert uuid.UUID(body["conversation_id"])  # a real id was assigned


async def test_chat_threads_context_into_the_ai_service(authed_client, scripted_provider):
    """End to end through HTTP: the tool loop runs against the caller's real
    accounts, with the account resolved from the session - not from the model."""
    client, _user = authed_client

    account = (
        await client.post("/api/v1/accounts", json={"name": "Checking", "currency": "USD"})
    ).json()

    provider = scripted_provider(
        # First turn: the model asks for a balance, naming no account.
        ModelResponse(tool_calls=[ToolCall(id="c1", name="get_balance", arguments={})]),
        ModelResponse(text="Your balance is available."),
    )

    resp = await client.post("/api/v1/chat", json={"message": "what's my balance?"})

    assert resp.status_code == 200, resp.text

    # The tool result fed back to the model carries this user's real account
    # and its real opening balance.
    tool_messages = [m for m in provider.calls[1] if m.role == "tool"]
    assert len(tool_messages) == 1
    payload = json.loads(tool_messages[0].content or "{}")

    assert payload["ok"] is True
    assert payload["result"]["account_id"] == account["id"]
    assert payload["result"]["balance_minor"] == OPENING_BALANCE_MINOR
    assert payload["result"]["source"] == "ledger"


@pytest.mark.parametrize("message", ["", "   ", "\n\t "])
async def test_chat_rejects_empty_message(authed_client, scripted_provider, message):
    """Blank and whitespace-only alike - never let an empty prompt reach the model."""
    client, _user = authed_client
    scripted_provider(ModelResponse(text="unused"))

    resp = await client.post("/api/v1/chat", json={"message": message})

    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "validation_error"


async def test_chat_rejects_oversized_message(authed_client, scripted_provider):
    client, _user = authed_client
    scripted_provider(ModelResponse(text="unused"))

    resp = await client.post("/api/v1/chat", json={"message": "x" * (MAX_MESSAGE_CHARS + 1)})

    assert resp.status_code == 422


async def test_chat_persists_conversation_across_turns(authed_client, scripted_provider):
    """The whole point of Step 5: a second turn against the same
    conversation_id sees the first turn, without the client resending it."""
    client, _user = authed_client
    scripted_provider(ModelResponse(text="first answer"))

    first = await client.post("/api/v1/chat", json={"message": "first question"})
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]

    scripted_provider(ModelResponse(text="second answer"))
    second = await client.post(
        "/api/v1/chat",
        json={"message": "second question", "conversation_id": conversation_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id

    history_resp = await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages")
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()

    assert [(m["role"], m["content"]) for m in history] == [
        ("user", "first question"),
        ("assistant", "first answer"),
        ("user", "second question"),
        ("assistant", "second answer"),
    ]


async def test_chat_with_unknown_conversation_id_is_not_found(authed_client, scripted_provider):
    client, _user = authed_client
    scripted_provider(ModelResponse(text="unused"))

    resp = await client.post(
        "/api/v1/chat",
        json={"message": "hi", "conversation_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "conversation_not_found"


async def test_tool_call_turns_are_persisted(authed_client, scripted_provider):
    """Tool-call round trips must survive a page refresh too, not just plain
    text turns - that's the whole reason messages.tool_calls is JSONB."""
    client, _user = authed_client

    scripted_provider(
        ModelResponse(tool_calls=[ToolCall(id="c1", name="get_balance", arguments={})]),
        ModelResponse(text="Soldul tău este disponibil."),
    )

    resp = await client.post("/api/v1/chat", json={"message": "care este soldul meu?"})
    assert resp.status_code == 200, resp.text
    conversation_id = resp.json()["conversation_id"]

    history_resp = await client.get(f"/api/v1/chat/conversations/{conversation_id}/messages")
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()

    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[0]["content"] == "care este soldul meu?"
    assert history[1]["tool_calls"][0]["name"] == "get_balance"
    assert history[1]["tool_calls"][0]["id"] == "c1"
    assert history[2]["name"] == "get_balance"
    assert history[2]["tool_call_id"] == "c1"
    assert history[3]["content"] == "Soldul tău este disponibil."


async def test_chat_isolates_users(authed_client_factory, scripted_provider):
    """User B cannot read user A's account, even naming its id explicitly."""
    alice_client, _alice = await authed_client_factory()
    bob_client, _bob = await authed_client_factory()

    alice_account = (
        await alice_client.post(
            "/api/v1/accounts", json={"name": "Alice Checking", "currency": "USD"}
        )
    ).json()

    # Bob's model tries to read Alice's account by id.
    provider = scripted_provider(
        ModelResponse(
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="get_balance",
                    arguments={"account_id": alice_account["id"]},
                )
            ]
        ),
        ModelResponse(text="I can only see your own accounts."),
    )

    resp = await bob_client.post("/api/v1/chat", json={"message": "balance of that account"})

    assert resp.status_code == 200, resp.text

    payload = json.loads(
        [m for m in provider.calls[1] if m.role == "tool"][0].content or "{}"
    )
    assert payload["ok"] is False
    assert "access denied" in payload["error"]
    # The refused identifier is never echoed back to the model.
    assert alice_account["id"] not in payload["error"]

    # And Alice's own request still works normally, in her own conversation.
    scripted_provider(ModelResponse(text="fine"))
    alice_resp = await alice_client.post("/api/v1/chat", json={"message": "hello"})
    assert alice_resp.status_code == 200
    assert alice_resp.json()["reply"] == "fine"
