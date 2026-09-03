"""`cancel_proposal` (Bug fix): a user who received a proposal earlier in a
conversation - possibly several turns ago, not just "immediately after" - can
now back out of it from chat itself, the same way propose_* creates one.

Proposals are seeded directly via proposals_service.create_proposal, same
convention as test_proposals_confirm.py: these tests are about the
cancellation gate itself (ownership + pending/expiry state), not about the
model successfully calling the tool through a full chat turn (that half is
already covered by test_propose_tools.py's pattern for propose_*).
"""

from app.ai.context import build_context
from app.ai.schemas import ModelResponse, ToolCall
from app.ai.tools.banking import CancelProposalTool
from app.modules.chat.proposals_service import create_proposal, mark_confirmed


async def _open_account(client, name="Checking", currency="RON"):
    resp = await client.post("/api/v1/accounts", json={"name": name, "currency": currency})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed(supabase, user, conversation, from_account, to_account, amount=10_000):
    return await create_proposal(
        supabase,
        user_id=str(user.id),
        conversation_id=conversation["id"],
        proposal_type="transfer",
        payload={
            "from_account_id": from_account["id"],
            "to_account_id": to_account["id"],
            "amount_minor": amount,
            "currency": "RON",
            "description": None,
        },
        summary=f"Transfer de {amount / 100:.2f} RON",
    )


async def _row(supabase, proposal_id):
    resp = (
        await supabase.table("proposals").select("*").eq("id", proposal_id).maybe_single().execute()
    )
    return resp.data


def _call(proposal_id: str | None = None) -> ToolCall:
    arguments = {} if proposal_id is None else {"proposal_id": proposal_id}
    return ToolCall(id="c1", name="cancel_proposal", arguments=arguments)


async def test_cancel_proposal_by_id_rejects_a_pending_proposal(
    authed_client, supabase, conversation_factory
):
    client, user = authed_client
    from_account = await _open_account(client, "Cont Curent")
    to_account = await _open_account(client, "Economii")
    conversation = await conversation_factory(user)
    proposal = await _seed(supabase, user, conversation, from_account, to_account)

    context = build_context(str(user.id), (), conversation_id=conversation["id"])
    result = await CancelProposalTool(supabase).execute(_call(proposal["id"]), context)

    assert result.ok, result.error
    assert result.data == {"proposal_id": proposal["id"], "status": "rejected"}

    row = await _row(supabase, proposal["id"])
    assert row["status"] == "rejected"
    assert row["rejected_at"] is not None


async def test_cancel_proposal_without_id_cancels_the_conversations_pending_one(
    authed_client, supabase, conversation_factory
):
    """The model does not need to have retained the exact proposal id from
    earlier in the conversation - omitting it resolves to the caller's own
    current pending proposal in this conversation, since create_proposal
    guarantees there is at most one."""
    client, user = authed_client
    from_account = await _open_account(client, "Cont Curent")
    to_account = await _open_account(client, "Economii")
    conversation = await conversation_factory(user)
    proposal = await _seed(supabase, user, conversation, from_account, to_account)

    context = build_context(str(user.id), (), conversation_id=conversation["id"])
    result = await CancelProposalTool(supabase).execute(_call(), context)

    assert result.ok, result.error
    assert result.data["proposal_id"] == proposal["id"]

    row = await _row(supabase, proposal["id"])
    assert row["status"] == "rejected"


async def test_cancel_proposal_works_in_a_later_turn_not_just_immediately_after(
    authed_client, supabase, conversation_factory
):
    """Reproduces the reported bug: a fresh Context (as build_context_for_user
    builds one per HTTP request - see chat/router.py) built well after the
    proposal was created must still be able to cancel it. Nothing about
    cancellation is scoped to "the same turn" - only to the (user,
    conversation, still-pending) triple."""
    client, user = authed_client
    from_account = await _open_account(client, "Cont Curent")
    to_account = await _open_account(client, "Economii")
    conversation = await conversation_factory(user)
    proposal = await _seed(supabase, user, conversation, from_account, to_account)

    # Simulates several intervening messages/turns: a brand new Context,
    # nothing carried over from the turn that created the proposal.
    later_context = build_context(str(user.id), (), conversation_id=conversation["id"])
    result = await CancelProposalTool(supabase).execute(_call(proposal["id"]), later_context)

    assert result.ok, result.error
    row = await _row(supabase, proposal["id"])
    assert row["status"] == "rejected"


async def test_cancel_proposal_rejects_another_users_proposal_id(
    authed_client, supabase, user_factory, conversation_factory
):
    """SECURITY: naming someone else's proposal id - guessed or otherwise -
    must not cancel it, and must not distinguish "exists but not yours" from
    "does not exist" in the error it returns."""
    client, alice = authed_client
    bob = await user_factory()
    alice_from = await _open_account(client, "Cont Curent")
    alice_to = await _open_account(client, "Economii")
    alice_conversation = await conversation_factory(alice)
    alice_proposal = await _seed(supabase, alice, alice_conversation, alice_from, alice_to)

    bob_conversation = await conversation_factory(bob)
    bob_context = build_context(str(bob.id), (), conversation_id=bob_conversation["id"])
    result = await CancelProposalTool(supabase).execute(_call(alice_proposal["id"]), bob_context)

    assert not result.ok
    assert "nu am găsit" in result.error.lower()

    row = await _row(supabase, alice_proposal["id"])
    assert row["status"] == "pending"


async def test_cancel_proposal_without_id_finds_nothing_for_another_users_conversation(
    authed_client, supabase, user_factory, conversation_factory
):
    """SECURITY: the id-less "cancel my current proposal" path is scoped by
    the caller's own user id AND conversation, not by conversation id alone -
    a bystander in (or a guess of) the same conversation id cannot use it to
    reach someone else's proposal."""
    client, alice = authed_client
    bob = await user_factory()
    alice_from = await _open_account(client, "Cont Curent")
    alice_to = await _open_account(client, "Economii")
    alice_conversation = await conversation_factory(alice)
    await _seed(supabase, alice, alice_conversation, alice_from, alice_to)

    # Bob, impersonating nobody, pointed at Alice's own conversation id.
    bob_context = build_context(str(bob.id), (), conversation_id=alice_conversation["id"])
    result = await CancelProposalTool(supabase).execute(_call(), bob_context)

    assert not result.ok
    assert "nu există nicio propunere" in result.error.lower()


async def test_cancel_proposal_leaves_an_already_confirmed_proposal_untouched(
    authed_client, supabase, conversation_factory
):
    client, user = authed_client
    from_account = await _open_account(client, "Cont Curent")
    to_account = await _open_account(client, "Economii")
    conversation = await conversation_factory(user)
    proposal = await _seed(supabase, user, conversation, from_account, to_account)
    await mark_confirmed(supabase, proposal, result={"already": "executed"})

    context = build_context(str(user.id), (), conversation_id=conversation["id"])
    result = await CancelProposalTool(supabase).execute(_call(proposal["id"]), context)

    assert not result.ok
    assert "nu mai este în așteptare" in result.error.lower()

    row = await _row(supabase, proposal["id"])
    assert row["status"] == "confirmed"


async def test_cancel_proposal_without_id_and_nothing_pending_fails_cleanly(
    supabase, authed_client, conversation_factory
):
    _client, user = authed_client
    conversation = await conversation_factory(user)
    context = build_context(str(user.id), (), conversation_id=conversation["id"])

    result = await CancelProposalTool(supabase).execute(_call(), context)

    assert not result.ok
    assert "nu există nicio propunere" in result.error.lower()


# ---------------------------------------------------------------------------
# Part 3 of the false-success bug fix: ChatResponse.resolved_proposal_id.
#
# A user can cancel a proposal from a LATER chat message - a different turn
# than the one that rendered its card - so the frontend can't rely on "the
# card just created this turn" the way it does for `proposal` on a fresh
# propose_* call. These drive cancel_proposal through the real /api/v1/chat
# endpoint (unlike the tool-level tests above) specifically to assert on
# what the HTTP response carries, since that's what frontend/app.js's
# resolveLivePendingProposalCard actually reads. See router.
# _extract_resolved_proposal and app.js's chat-send handler.
# ---------------------------------------------------------------------------


async def test_chat_cancel_proposal_surfaces_resolved_proposal_on_response(
    authed_client, scripted_provider, supabase, conversation_factory
):
    client, user = authed_client
    from_account = await _open_account(client, "Cont Curent")
    to_account = await _open_account(client, "Economii")
    conversation = await conversation_factory(user)
    proposal = await _seed(supabase, user, conversation, from_account, to_account)

    scripted_provider(
        # "anulează propunerea" matches no keyword rule (see INSIGHTS_
        # ROUTING_RULES's `anul ` comment in insights_agent.py - deliberately
        # NOT "anulează", to avoid claiming this exact phrase), so
        # orchestrator._classify_with_model makes its own `.complete()` call
        # before the chosen agent's tool loop starts - one extra scripted
        # response, ahead of the actual tool call.
        ModelResponse(text="banking"),
        ModelResponse(tool_calls=[_call(proposal["id"])]),
        ModelResponse(text="Am anulat propunerea."),
    )

    resp = await client.post(
        "/api/v1/chat",
        json={"message": "anulează propunerea", "conversation_id": conversation["id"]},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["resolved_proposal_id"] == proposal["id"]
    assert body["resolved_proposal_status"] == "rejected"
    # This turn didn't propose anything new - only cancelled an old one.
    assert body["proposal"] is None

    row = await _row(supabase, proposal["id"])
    assert row["status"] == "rejected"


async def test_chat_without_cancel_proposal_leaves_resolved_proposal_id_null(
    authed_client, scripted_provider, supabase, conversation_factory
):
    """An ordinary turn (no cancel_proposal call at all) must not populate
    resolved_proposal_id - it's additive/optional, same as `proposal`."""
    client, user = authed_client
    conversation = await conversation_factory(user)

    scripted_provider(ModelResponse(text="Salut!"))

    resp = await client.post(
        "/api/v1/chat",
        json={"message": "salut", "conversation_id": conversation["id"]},
    )
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["resolved_proposal_id"] is None
    assert body["resolved_proposal_status"] is None
