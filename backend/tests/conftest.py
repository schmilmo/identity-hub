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
# Tests use the local AES-GCM backend so they need no Vault container.
os.environ["CRYPTO_BACKEND"] = "local"

import fakeredis.aioredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import redis_client  # noqa: E402
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
def fake_redis():
    """Back sessions with an in-memory fake Redis — no Redis container needed,
    and each test starts with a clean session store."""
    redis_client._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield
    redis_client._client = None


@pytest.fixture(autouse=True)
def mock_jira(monkeypatch):
    """Replace Jira network calls with an in-memory fake Jira.

    Issues are stored keyed by site_url, so two users on *different* Jira
    sites are isolated, while the same site is shared — mirroring real Jira
    and letting us test tenancy without a network. Patching the methods on the
    class object covers every call site (routers and service layer).
    """
    counter = itertools.count(1)
    # site_url -> list of stored issues (most-recent-last)
    store: dict[str, list[dict]] = {}

    async def fake_verify(self):
        return {"accountId": "test-account"}

    async def fake_list_projects(self):
        return [
            {"key": "NHI", "name": "NHI Findings"},
            {"key": "SEC", "name": "Security"},
        ]

    async def fake_create_issue(
        self, project_key, summary, description,
        labels=None, priority=None, extra_fields=None,
    ):
        all_labels = list(dict.fromkeys([jc.APP_LABEL, *(labels or [])]))
        n = next(counter)
        key = f"{project_key}-{n}"
        issue = {
            "key": key,
            "url": f"https://{self._site_url}/browse/{key}",
            "title": summary,
            "created": f"2026-06-09T12:00:{n:02d}+00:00",
            "labels": all_labels,
            "project_key": project_key,
            "priority": priority,
            "description": description,
            "extra_fields": extra_fields or {},
            "remote_links": [],
        }
        store.setdefault(self._site_url, []).append(issue)
        return {"key": key, "url": issue["url"], "labels": all_labels}

    async def fake_add_remote_link(self, issue_key, url, title):
        for issue in store.get(self._site_url, []):
            if issue["key"] == issue_key:
                issue["remote_links"].append({"url": url, "title": title})

    async def fake_search(self, project_key=None, limit=10):
        issues = [
            i
            for i in store.get(self._site_url, [])
            if (project_key is None or i["project_key"] == project_key)
            and jc.APP_LABEL in i["labels"]
        ]
        issues = list(reversed(issues))[:limit]  # newest first
        keys = ("key", "url", "title", "created", "labels", "project_key")
        return [{k: i[k] for k in keys} for i in issues]

    async def fake_get_issue(self, issue_key, extra_field_ids):
        for i in store.get(self._site_url, []):
            if i["key"] == issue_key:
                return {
                    "key": i["key"],
                    "url": i["url"],
                    "title": i["title"],
                    "description": i["description"],
                    "labels": i["labels"],
                    "priority": i.get("priority"),
                    "status": "To Do",
                    "assignee": None,
                    "created": i["created"],
                    "custom_fields": {
                        cf: i["extra_fields"].get(cf) for cf in extra_field_ids
                    },
                }
        raise jc.JiraError(f"Issue {issue_key} not found in Jira.", status=404)

    monkeypatch.setattr(jc.JiraClient, "verify", fake_verify)
    monkeypatch.setattr(jc.JiraClient, "list_projects", fake_list_projects)
    monkeypatch.setattr(jc.JiraClient, "create_issue", fake_create_issue)
    monkeypatch.setattr(jc.JiraClient, "add_remote_link", fake_add_remote_link)
    monkeypatch.setattr(jc.JiraClient, "search_app_issues", fake_search)
    monkeypatch.setattr(jc.JiraClient, "get_issue", fake_get_issue)
    # Expose the store for tests that want to inspect what was sent to Jira.
    return store


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
