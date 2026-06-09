from tests.conftest import register


def test_register_login_me_logout(client):
    register(client)

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"
    assert me.json()["jira_connected"] is False

    assert client.post("/auth/logout").status_code == 204
    # Cookie cleared → no longer authenticated.
    assert client.get("/auth/me").status_code == 401


def test_duplicate_email_rejected(client):
    register(client)
    resp = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "anotherpass"},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]


def test_login_wrong_password(client):
    register(client)
    client.post("/auth/logout")
    resp = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "wrongpass"},
    )
    assert resp.status_code == 401
    # Message must not reveal whether the email exists.
    assert resp.json()["detail"] == "Invalid email or password."


def test_login_unknown_email(client):
    resp = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "whatever123"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password."


def test_short_password_rejected(client):
    resp = client.post(
        "/auth/register", json={"email": "a@b.com", "password": "short"}
    )
    assert resp.status_code == 422


def test_me_requires_auth(client):
    assert client.get("/auth/me").status_code == 401
