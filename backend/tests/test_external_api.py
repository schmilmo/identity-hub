from tests.conftest import connect_jira, register


def _make_api_key(client, name="ci"):
    resp = client.post("/api-keys", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()["api_key"]


def test_create_finding_via_api(client):
    register(client)
    connect_jira(client)
    key = _make_api_key(client)

    resp = client.post(
        "/api/v1/findings",
        headers={"Authorization": f"Bearer {key}"},
        json={"project_key": "NHI", "title": "Scanner finding", "description": "d"},
    )
    assert resp.status_code == 201, resp.text
    assert "identityhub" in resp.json()["labels"]

    # Shows up in the UI's recent list — same Jira workspace.
    recent = client.get("/findings", params={"project_key": "NHI"}).json()
    assert recent[0]["title"] == "Scanner finding"


def test_missing_authorization_header(client):
    resp = client.post(
        "/api/v1/findings",
        json={"project_key": "NHI", "title": "t", "description": ""},
    )
    assert resp.status_code == 401


def test_invalid_api_key(client):
    resp = client.post(
        "/api/v1/findings",
        headers={"Authorization": "Bearer ih_live_bogus"},
        json={"project_key": "NHI", "title": "t", "description": ""},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid API key"


def test_revoked_key_rejected(client):
    register(client)
    connect_jira(client)
    create = client.post("/api-keys", json={"name": "temp"}).json()
    key = create["api_key"]
    assert client.delete(f"/api-keys/{create['id']}").status_code == 204

    resp = client.post(
        "/api/v1/findings",
        headers={"Authorization": f"Bearer {key}"},
        json={"project_key": "NHI", "title": "t", "description": ""},
    )
    assert resp.status_code == 401


def test_validation_error_is_422_with_message(client):
    register(client)
    connect_jira(client)
    key = _make_api_key(client)
    resp = client.post(
        "/api/v1/findings",
        headers={"Authorization": f"Bearer {key}"},
        json={"project_key": "NHI"},  # missing title
    )
    assert resp.status_code == 422
    assert "title" in resp.json()["detail"]


def test_api_key_without_jira_returns_409(client):
    register(client)  # no Jira connected
    key = _make_api_key(client)
    resp = client.post(
        "/api/v1/findings",
        headers={"Authorization": f"Bearer {key}"},
        json={"project_key": "NHI", "title": "t", "description": ""},
    )
    assert resp.status_code == 409
