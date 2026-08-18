async def test_get_my_profile(authed_client):
    client, user = authed_client
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(user.id)
    assert body["email"] == user.email
    assert body["full_name"] == user.full_name


async def test_update_my_profile(authed_client):
    client, _user = authed_client
    resp = await client.patch("/api/v1/users/me", json={"full_name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "New Name"

    resp = await client.get("/api/v1/users/me")
    assert resp.json()["full_name"] == "New Name"


async def test_users_me_requires_authentication(client):
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401
