from tests.conftest import connect_jira, register


def test_connect_jira_sets_flag(client):
    register(client)
    connect_jira(client)
    assert client.get("/auth/me").json()["jira_connected"] is True


def test_list_projects(client):
    register(client)
    connect_jira(client)
    resp = client.get("/jira/projects")
    assert resp.status_code == 200
    keys = [p["key"] for p in resp.json()]
    assert "NHI" in keys


def test_create_finding_and_recent(client):
    register(client)
    connect_jira(client)

    resp = client.post(
        "/findings",
        json={"project_key": "NHI", "title": "Stale SA", "description": "90d idle"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["jira_issue_key"].startswith("NHI-")
    assert body["jira_issue_url"].endswith(body["jira_issue_key"])
    assert body["source"] == "ui"

    recent = client.get("/findings", params={"project_key": "NHI"})
    assert recent.status_code == 200
    assert len(recent.json()) == 1
    assert recent.json()[0]["title"] == "Stale SA"


def test_recent_capped_at_ten_and_ordered(client):
    register(client)
    connect_jira(client)
    for i in range(12):
        client.post(
            "/findings",
            json={"project_key": "NHI", "title": f"finding {i}", "description": ""},
        )
    recent = client.get("/findings", params={"project_key": "NHI"}).json()
    assert len(recent) == 10  # only the 10 most recent
    # Most recent first.
    assert recent[0]["title"] == "finding 11"


def test_recent_scoped_by_project(client):
    register(client)
    connect_jira(client)
    client.post("/findings", json={"project_key": "NHI", "title": "n", "description": ""})
    client.post("/findings", json={"project_key": "SEC", "title": "s", "description": ""})
    assert len(client.get("/findings", params={"project_key": "NHI"}).json()) == 1
    assert len(client.get("/findings", params={"project_key": "SEC"}).json()) == 1


def test_create_finding_without_jira_returns_409(client):
    register(client)
    resp = client.post(
        "/findings", json={"project_key": "NHI", "title": "x", "description": ""}
    )
    assert resp.status_code == 409
    assert "Connect Jira" in resp.json()["detail"]


def test_findings_require_auth(client):
    assert client.get("/findings", params={"project_key": "NHI"}).status_code == 401
