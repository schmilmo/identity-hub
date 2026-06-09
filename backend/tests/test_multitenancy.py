"""The security-critical property: no data crosses tenant boundaries.

Each test uses two independent clients (separate cookie jars) for two users.
"""
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import connect_jira, register


def _client():
    return TestClient(app)


def test_findings_isolated_between_users(client):
    # User A
    register(client, email="a@example.com")
    connect_jira(client, email="a@example.com")
    client.post(
        "/findings", json={"project_key": "NHI", "title": "A-secret", "description": ""}
    )

    # User B — separate session.
    with _client() as b:
        register(b, email="b@example.com")
        connect_jira(b, email="b@example.com")
        recent_b = b.get("/findings", params={"project_key": "NHI"}).json()
        # B must not see A's ticket even though both use project "NHI".
        assert recent_b == []

        b.post(
            "/findings",
            json={"project_key": "NHI", "title": "B-secret", "description": ""},
        )
        titles_b = [t["title"] for t in b.get("/findings", params={"project_key": "NHI"}).json()]
        assert titles_b == ["B-secret"]

    # A still sees only its own.
    titles_a = [t["title"] for t in client.get("/findings", params={"project_key": "NHI"}).json()]
    assert titles_a == ["A-secret"]


def test_cannot_revoke_another_users_api_key(client):
    # User A creates a key.
    register(client, email="a@example.com")
    key_id = client.post("/api-keys", json={"name": "a-key"}).json()["id"]

    # User B tries to revoke it → 404 (existence not leaked, not 403).
    with _client() as b:
        register(b, email="b@example.com")
        resp = b.delete(f"/api-keys/{key_id}")
        assert resp.status_code == 404

    # A's key is still listed and active.
    keys = client.get("/api-keys").json()
    assert keys[0]["id"] == key_id
    assert keys[0]["revoked_at"] is None


def test_api_key_routes_other_tenants_finding_to_correct_owner(client):
    # A's API key must create tickets under A, never B.
    register(client, email="a@example.com")
    connect_jira(client, email="a@example.com")
    a_key = client.post("/api-keys", json={"name": "a"}).json()["api_key"]

    with _client() as b:
        register(b, email="b@example.com")
        connect_jira(b, email="b@example.com")

        # Use A's key while holding B's session cookie.
        b.post(
            "/api/v1/findings",
            headers={"Authorization": f"Bearer {a_key}"},
            json={"project_key": "NHI", "title": "routed-to-A", "description": ""},
        )
        # B's own list stays empty — the key's owner (A) got the ticket.
        assert b.get("/findings", params={"project_key": "NHI"}).json() == []

    titles_a = [t["title"] for t in client.get("/findings", params={"project_key": "NHI"}).json()]
    assert titles_a == ["routed-to-A"]
