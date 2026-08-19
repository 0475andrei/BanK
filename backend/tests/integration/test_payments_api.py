async def _open_account(client, name="Checking", currency="USD"):
    resp = await client.post("/api/v1/accounts", json={"name": name, "currency": currency})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_payment_moves_balance_between_users(authed_client, authed_client_factory):
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")

    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")

    resp = await payer.post(
        "/api/v1/payments",
        json={
            "from_account_id": payer_account["id"],
            "to_iban": payee_account["iban"],
            "beneficiary_name": "Payee Person",
            "amount_minor": 1_000,
        },
        headers={"Idempotency-Key": "payment-1"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["to_account_id"] == payee_account["id"]
    assert body["to_iban"] == payee_account["iban"]
    assert body["amount_minor"] == 1_000
    assert body["status"] == "completed"

    payer_after = (await payer.get(f"/api/v1/accounts/{payer_account['id']}")).json()
    payee_after = (await payee.get(f"/api/v1/accounts/{payee_account['id']}")).json()
    assert payer_after["balance_minor"] == payer_account["balance_minor"] - 1_000
    assert payee_after["balance_minor"] == payee_account["balance_minor"] + 1_000


async def test_create_payment_saves_and_updates_beneficiary(authed_client, authed_client_factory):
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")

    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")

    await payer.post(
        "/api/v1/payments",
        json={
            "from_account_id": payer_account["id"],
            "to_iban": payee_account["iban"],
            "beneficiary_name": "First Name",
            "amount_minor": 500,
        },
        headers={"Idempotency-Key": "payment-a"},
    )

    contacts = (await payer.get("/api/v1/beneficiaries")).json()
    assert len(contacts) == 1
    assert contacts[0]["iban"] == payee_account["iban"]
    assert contacts[0]["display_name"] == "First Name"

    # Paying the same IBAN again with a different name updates the contact,
    # not duplicates it.
    await payer.post(
        "/api/v1/payments",
        json={
            "from_account_id": payer_account["id"],
            "to_iban": payee_account["iban"],
            "beneficiary_name": "Updated Name",
            "amount_minor": 100,
        },
        headers={"Idempotency-Key": "payment-b"},
    )
    contacts = (await payer.get("/api/v1/beneficiaries")).json()
    assert len(contacts) == 1
    assert contacts[0]["display_name"] == "Updated Name"


async def test_payment_rejects_unknown_iban(authed_client):
    client, _user = authed_client
    account = await _open_account(client)

    resp = await client.post(
        "/api/v1/payments",
        json={
            "from_account_id": account["id"],
            "to_iban": "RO49AAAA1B31007593840000",
            "beneficiary_name": "Nobody",
            "amount_minor": 100,
        },
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "iban_not_found"


async def test_payment_rejects_unowned_from_account(authed_client, authed_client_factory):
    owner, _owner_user = authed_client
    owner_account = await _open_account(owner)

    other, _other_user = await authed_client_factory()
    other_account = await _open_account(other)

    resp = await other.post(
        "/api/v1/payments",
        json={
            "from_account_id": owner_account["id"],
            "to_iban": other_account["iban"],
            "beneficiary_name": "Someone",
            "amount_minor": 100,
        },
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 404


async def test_payment_rejects_same_account(authed_client):
    client, _user = authed_client
    account = await _open_account(client)

    resp = await client.post(
        "/api/v1/payments",
        json={
            "from_account_id": account["id"],
            "to_iban": account["iban"],
            "beneficiary_name": "Myself",
            "amount_minor": 100,
        },
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 422


async def test_payment_rejects_currency_mismatch(authed_client, authed_client_factory):
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer", currency="USD")

    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee", currency="EUR")

    resp = await payer.post(
        "/api/v1/payments",
        json={
            "from_account_id": payer_account["id"],
            "to_iban": payee_account["iban"],
            "beneficiary_name": "Payee",
            "amount_minor": 100,
        },
        headers={"Idempotency-Key": "k1"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "currency_mismatch"


async def test_payment_requires_idempotency_key(authed_client, authed_client_factory):
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer)
    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee)

    resp = await payer.post(
        "/api/v1/payments",
        json={
            "from_account_id": payer_account["id"],
            "to_iban": payee_account["iban"],
            "beneficiary_name": "Payee",
            "amount_minor": 100,
        },
    )
    assert resp.status_code == 400


async def test_payments_and_beneficiaries_require_authentication(client):
    resp = await client.get("/api/v1/payments")
    assert resp.status_code == 401

    resp = await client.get("/api/v1/beneficiaries")
    assert resp.status_code == 401
