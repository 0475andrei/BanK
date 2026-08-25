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


async def _pay(payer, payer_account, payee_account, amount_minor, key, **extra):
    return await payer.post(
        "/api/v1/payments",
        json={
            "from_account_id": payer_account["id"],
            "to_iban": payee_account["iban"],
            "beneficiary_name": "Netflix",
            "amount_minor": amount_minor,
            **extra,
        },
        headers={"Idempotency-Key": key},
    )


async def _mark_as_subscription(client, iban, display_name="Netflix", **extra):
    resp = await client.post(
        "/api/v1/beneficiaries",
        json={"iban": iban, "display_name": display_name, "is_subscription": True, **extra},
    )
    assert resp.status_code == 201, resp.text


async def test_payment_blocks_subscription_price_increase(authed_client, authed_client_factory):
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")
    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")
    await _mark_as_subscription(payer, payee_account["iban"])

    # Two prior payments at the same amount establish the "recurring at
    # this price" pattern (see _detect_subscription_price_increase).
    assert (await _pay(payer, payer_account, payee_account, 4_000, "p1")).status_code == 201
    assert (await _pay(payer, payer_account, payee_account, 4_000, "p2")).status_code == 201

    resp = await _pay(payer, payer_account, payee_account, 6_000, "p3")
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["error"]["code"] == "subscription_price_increase"
    assert body["error"]["details"]["previous_amount_minor"] == 4_000
    assert body["error"]["details"]["new_amount_minor"] == 6_000
    assert body["error"]["details"]["beneficiary_name"] == "Netflix"

    # Blocked, so no third payment actually happened.
    payer_after = (await payer.get(f"/api/v1/accounts/{payer_account['id']}")).json()
    assert payer_after["balance_minor"] == payer_account["balance_minor"] - 8_000


async def test_payment_price_increase_can_be_confirmed_and_retried(
    authed_client, authed_client_factory
):
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")
    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")
    await _mark_as_subscription(payer, payee_account["iban"])

    await _pay(payer, payer_account, payee_account, 4_000, "q1")
    await _pay(payer, payer_account, payee_account, 4_000, "q2")

    blocked = await _pay(payer, payer_account, payee_account, 6_000, "q3")
    assert blocked.status_code == 409

    # Same idempotency key, now with the user's explicit go-ahead.
    resp = await _pay(
        payer, payer_account, payee_account, 6_000, "q3", confirm_price_increase=True
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["amount_minor"] == 6_000


async def test_payment_price_increase_includes_saved_website(
    authed_client, authed_client_factory
):
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")
    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")

    await _mark_as_subscription(payer, payee_account["iban"], website="https://netflix.com")
    await _pay(payer, payer_account, payee_account, 4_000, "r1")
    await _pay(payer, payer_account, payee_account, 4_000, "r2")

    resp = await _pay(payer, payer_account, payee_account, 6_000, "r3")
    assert resp.status_code == 409
    assert resp.json()["error"]["details"]["website"] == "https://netflix.com"


async def test_payment_without_recurring_history_is_not_blocked(
    authed_client, authed_client_factory
):
    """A single prior payment isn't a "pattern" yet - only the second
    repeat proves it's recurring, same threshold as the tool this reuses
    the logic from (detect_recurring_payments)."""
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")
    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")

    await _pay(payer, payer_account, payee_account, 4_000, "s1")
    resp = await _pay(payer, payer_account, payee_account, 6_000, "s2")
    assert resp.status_code == 201, resp.text


async def test_payment_to_an_unmarked_person_is_never_blocked(
    authed_client, authed_client_factory
):
    """The whole point of is_subscription: a friend/family member paid the
    same recurring amount twice, then a higher one (e.g. splitting a
    bigger bill), must NOT be mistaken for "a subscription raised its
    price" just because the payment pattern looks the same. Only a contact
    explicitly marked is_subscription can ever trigger the block - see
    test_payment_blocks_subscription_price_increase for the contrasting
    case with the same amounts, marked."""
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")
    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")

    await _pay(payer, payer_account, payee_account, 4_000, "t1", beneficiary_name="Ana")
    await _pay(payer, payer_account, payee_account, 4_000, "t2", beneficiary_name="Ana")
    resp = await _pay(payer, payer_account, payee_account, 6_000, "t3", beneficiary_name="Ana")
    assert resp.status_code == 201, resp.text


async def test_payment_to_a_saved_person_marked_not_subscription_is_never_blocked(
    authed_client, authed_client_factory
):
    """Same as above, but the contact IS saved (auto-saved by the payments
    themselves) - is_subscription defaults to false, so it still must not
    block."""
    payer, _payer_user = authed_client
    payer_account = await _open_account(payer, "Payer")
    payee, _payee_user = await authed_client_factory()
    payee_account = await _open_account(payee, "Payee")

    await _pay(payer, payer_account, payee_account, 4_000, "u1", beneficiary_name="Ana")
    await _pay(payer, payer_account, payee_account, 4_000, "u2", beneficiary_name="Ana")

    contacts = (await payer.get("/api/v1/beneficiaries")).json()
    assert contacts[0]["is_subscription"] is False

    resp = await _pay(payer, payer_account, payee_account, 6_000, "u3", beneficiary_name="Ana")
    assert resp.status_code == 201, resp.text


async def test_payments_and_beneficiaries_require_authentication(client):
    resp = await client.get("/api/v1/payments")
    assert resp.status_code == 401

    resp = await client.get("/api/v1/beneficiaries")
    assert resp.status_code == 401
