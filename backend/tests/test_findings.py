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
    # The marker label is always present (how the recent view finds it).
    assert "identityhub" in body["labels"]

    recent = client.get("/findings", params={"project_key": "NHI"})
    assert recent.status_code == 200
    assert len(recent.json()) == 1
    assert recent.json()[0]["title"] == "Stale SA"


def test_custom_labels_and_marker(client, mock_jira):
    register(client)
    connect_jira(client)
    resp = client.post(
        "/findings",
        json={
            "project_key": "NHI",
            "title": "t",
            "description": "",
            "labels": ["prod", "over privileged"],  # space gets normalized
        },
    )
    assert resp.status_code == 201
    labels = resp.json()["labels"]
    assert labels[0] == "identityhub"  # marker first
    assert "prod" in labels
    assert "over-privileged" in labels  # space -> hyphen


def test_nhi_context_rendered_into_description(client, mock_jira):
    register(client)
    connect_jira(client)
    client.post(
        "/findings",
        json={
            "project_key": "NHI",
            "title": "t",
            "description": "Base details.",
            "resource": "svc-deploy-prod",
            "category": "Stale service account",
            "environment": "aws-prod",
        },
    )
    # Inspect what was sent to the fake Jira.
    sent = mock_jira["acme.atlassian.net"][-1]["description"]
    assert "Base details." in sent
    assert "NHI Finding Details:" in sent
    assert "Affected resource: svc-deploy-prod" in sent
    assert "Environment: aws-prod" in sent


def test_priority_forwarded(client, mock_jira):
    register(client)
    connect_jira(client)
    client.post(
        "/findings",
        json={"project_key": "NHI", "title": "t", "priority": "High"},
    )
    sent = mock_jira["acme.atlassian.net"][-1]
    assert sent["priority"] == "High"


def test_cross_reference_link_added(client, mock_jira):
    register(client)
    connect_jira(client)
    client.post("/findings", json={"project_key": "NHI", "title": "t"})
    links = mock_jira["acme.atlassian.net"][-1]["remote_links"]
    assert len(links) == 1
    assert links[0]["title"] == "View in IdentityHub"
    assert "project=NHI" in links[0]["url"]


def test_invalid_priority_rejected(client):
    register(client)
    connect_jira(client)
    resp = client.post(
        "/findings",
        json={"project_key": "NHI", "title": "t", "priority": "Critical"},
    )
    assert resp.status_code == 422


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


def test_list_all_projects_when_project_omitted(client):
    register(client)
    connect_jira(client)
    client.post("/findings", json={"project_key": "NHI", "title": "n", "description": ""})
    client.post("/findings", json={"project_key": "SEC", "title": "s", "description": ""})
    # No project_key → findings across all projects.
    rows = client.get("/findings").json()
    assert {r["project_key"] for r in rows} == {"NHI", "SEC"}
    assert len(rows) == 2


def test_finding_detail(client):
    register(client)
    connect_jira(client)
    created = client.post(
        "/findings",
        json={
            "project_key": "NHI",
            "title": "Stale SA",
            "description": "90d idle",
            "labels": ["aws"],
            "priority": "High",
        },
    ).json()
    key = created["jira_issue_key"]

    detail = client.get(f"/findings/{key}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["jira_issue_key"] == key
    assert body["title"] == "Stale SA"
    assert "90d idle" in body["description"]
    assert body["priority"] == "High"
    assert body["jira_issue_url"].endswith(key)


def test_finding_detail_requires_auth(client):
    assert client.get("/findings/NHI-1").status_code == 401


def test_create_finding_without_jira_returns_409(client):
    register(client)
    resp = client.post(
        "/findings", json={"project_key": "NHI", "title": "x", "description": ""}
    )
    assert resp.status_code == 409
    assert "Connect Jira" in resp.json()["detail"]


def test_findings_require_auth(client):
    assert client.get("/findings", params={"project_key": "NHI"}).status_code == 401
