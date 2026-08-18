from app.modules.cards.card_numbers import luhn_is_valid


async def _open_account(client, name="Checking", currency="USD"):
    resp = await client.post("/api/v1/accounts", json={"name": name, "currency": currency})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_issue_card_returns_full_number_once(authed_client):
    client, _user = authed_client
    account = await _open_account(client)

    resp = await client.post("/api/v1/cards", json={"account_id": account["id"]})
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert luhn_is_valid(body["card_number"])
    assert len(body["card_number"]) == 16
    assert body["card_number"].endswith(body["last4"])
    assert body["status"] == "active"
    assert body["account_id"] == account["id"]


async def test_list_cards_never_includes_full_number(authed_client):
    client, _user = authed_client
    account = await _open_account(client)
    await client.post("/api/v1/cards", json={"account_id": account["id"]})

    resp = await client.get("/api/v1/cards")
    assert resp.status_code == 200
    cards = resp.json()
    assert len(cards) == 1
    assert "card_number" not in cards[0]
    assert len(cards[0]["last4"]) == 4


async def test_cancel_card(authed_client):
    client, _user = authed_client
    account = await _open_account(client)
    issued = (await client.post("/api/v1/cards", json={"account_id": account["id"]})).json()

    resp = await client.delete(f"/api/v1/cards/{issued['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Cancelling again is a harmless no-op, not an error.
    resp = await client.delete(f"/api/v1/cards/{issued['id']}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    # Still listed (audit trail), just shown as cancelled.
    cards = (await client.get("/api/v1/cards")).json()
    assert cards[0]["status"] == "cancelled"


async def test_cancel_unknown_card_is_404(authed_client):
    client, _user = authed_client
    resp = await client.delete("/api/v1/cards/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_issue_card_rejects_closed_account(authed_client):
    client, _user = authed_client
    account = await _open_account(client)
    await client.post(f"/api/v1/accounts/{account['id']}/close")

    resp = await client.post("/api/v1/cards", json={"account_id": account["id"]})
    assert resp.status_code == 409


async def test_issue_card_rejects_unowned_account(authed_client, authed_client_factory):
    owner_client, _owner = authed_client
    account = await _open_account(owner_client)

    other_client, _other = await authed_client_factory()
    resp = await other_client.post("/api/v1/cards", json={"account_id": account["id"]})
    assert resp.status_code == 404


async def test_cards_require_authentication(client):
    resp = await client.get("/api/v1/cards")
    assert resp.status_code == 401
