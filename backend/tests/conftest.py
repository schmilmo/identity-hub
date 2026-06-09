"""Test fixtures.

Tests run against a file-based SQLite database (fast, no container) and a
fully mocked Jira client, so the suite needs no network or Postgres. The DB
URL is set before importing the app so the engine binds to SQLite.
"""
import itertools
import os
import pathlib

# Must be set before importing app.* (engine is created at import time).
_TEST_DB = pathlib.Path(__file__).parent / "test_app.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB}"
os.environ["APP_ENCRYPTION_KEY"] = "test-encryption-key-deterministic-but-fine"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import jira_client as jc  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Start every test from an empty database file."""
    if _TEST_DB.exists():
        _TEST_DB.unlink()
    yield
    if _TEST_DB.exists():
        _TEST_DB.unlink()


@pytest.fixture(autouse=True)
def mock_jira(monkeypatch):
    """Replace Jira network calls with in-process fakes.

    Patching the methods on the class object covers every call site, since
    both the routers and the service layer reference the same JiraClient.
    """
    counter = itertools.count(1)

    async def fake_verify(self):
        return {"accountId": "test-account"}

    async def fake_list_projects(self):
        return [
            {"key": "NHI", "name": "NHI Findings"},
            {"key": "SEC", "name": "Security"},
        ]

    async def fake_create_issue(self, project_key, summary, description):
        n = next(counter)
        key = f"{project_key}-{n}"
        return {"key": key, "url": f"https://{self._site_url}/browse/{key}"}

    monkeypatch.setattr(jc.JiraClient, "verify", fake_verify)
    monkeypatch.setattr(jc.JiraClient, "list_projects", fake_list_projects)
    monkeypatch.setattr(jc.JiraClient, "create_issue", fake_create_issue)


@pytest.fixture
def client():
    # The context manager triggers lifespan → init_db (creates tables).
    with TestClient(app) as c:
        yield c


def register(client, email="user@example.com", password="supersecret"):
    """Helper: register a user; the client retains the session cookie."""
    resp = client.post(
        "/auth/register", json={"email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def connect_jira(client, site="acme.atlassian.net", email="user@example.com"):
    resp = client.post(
        "/jira/connect",
        json={"site_url": site, "jira_email": email, "api_token": "tok-123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
