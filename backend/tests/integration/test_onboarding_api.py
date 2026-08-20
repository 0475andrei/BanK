"""POST /api/v1/onboarding/chat - Comodul, the pre-auth registration
assistant. Always a scripted MockProvider (see scripted_provider in
conftest.py), same seam test_chat_api.py uses - nothing here touches Azure
or the network.
"""

from app.ai.schemas import ModelResponse, ToolCall


async def test_onboarding_chat_requires_no_authentication(client):
    resp = await client.post("/api/v1/onboarding/chat", json={"message": "Salut"})
    assert resp.status_code != 401


async def test_onboarding_chat_returns_reply_and_history(client, scripted_provider):
    scripted_provider(ModelResponse(text="Salut! Care este numele tău?"))

    resp = await client.post("/api/v1/onboarding/chat", json={"message": "Salut"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == "Salut! Care este numele tău?"
    assert body["collected_fields"] is None
    roles = [m["role"] for m in body["history"]]
    assert roles == ["user", "assistant"]
    assert body["history"][0]["content"] == "Salut"


async def test_onboarding_chat_continues_from_client_held_history(client, scripted_provider):
    scripted_provider(ModelResponse(text="Perfect, mulțumesc!"))

    prior_history = [
        {"role": "user", "content": "Salut", "tool_calls": [], "tool_call_id": None, "name": None},
        {
            "role": "assistant",
            "content": "Salut! Care este numele tău?",
            "tool_calls": [],
            "tool_call_id": None,
            "name": None,
        },
    ]

    resp = await client.post(
        "/api/v1/onboarding/chat",
        json={"message": "Andrei Popescu", "history": prior_history},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    roles = [m["role"] for m in body["history"]]
    assert roles == ["user", "assistant", "user", "assistant"]


async def test_onboarding_chat_surfaces_collected_fields_after_propose_registration(
    client, scripted_provider
):
    fields = {
        "email": "andrei@example.com",
        "password": "correct horse",
        "first_name": "Andrei",
        "last_name": "Popescu",
        "national_id": "1900712345678",
        "phone": None,
        "address": None,
        "referral_code": None,
    }
    scripted_provider(
        ModelResponse(
            tool_calls=[ToolCall(id="c1", name="propose_registration", arguments=fields)]
        ),
        ModelResponse(text="Poți confirma crearea contului cu aceste date?"),
    )

    resp = await client.post("/api/v1/onboarding/chat", json={"message": "Atât e tot."})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["reply"] == "Poți confirma crearea contului cu aceste date?"
    assert body["collected_fields"] == fields


async def test_onboarding_chat_rejects_empty_message(client):
    resp = await client.post("/api/v1/onboarding/chat", json={"message": "   "})
    assert resp.status_code == 422


async def test_onboarding_chat_surfaces_account_conflict_for_existing_email(
    client, scripted_provider, user_factory
):
    existing = await user_factory(email="already-here@example.com")

    scripted_provider(
        ModelResponse(
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="check_existing_account",
                    arguments={"email": existing.email, "national_id": "1900712345678"},
                )
            ]
        ),
        ModelResponse(text="Se pare că ai deja un cont cu acest email."),
    )

    resp = await client.post(
        "/api/v1/onboarding/chat", json={"message": f"Email-ul meu e {existing.email}."}
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["account_conflict"] == {
        "exists": True,
        "matched_field": "email",
        "email": existing.email,
    }
    # A conflict is a dead end for THIS interview - propose_registration
    # was never called, so there's nothing to confirm.
    assert body["collected_fields"] is None


async def test_onboarding_chat_no_conflict_for_a_fresh_email_and_cnp(client, scripted_provider):
    scripted_provider(
        ModelResponse(
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="check_existing_account",
                    arguments={"email": "brand-new@example.com", "national_id": "1900712345678"},
                )
            ]
        ),
        ModelResponse(text="Perfect, nu ai deja un cont. Cum te numești?"),
    )

    resp = await client.post(
        "/api/v1/onboarding/chat", json={"message": "brand-new@example.com, CNP 1900712345678"}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["account_conflict"] is None
