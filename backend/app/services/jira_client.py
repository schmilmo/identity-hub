"""Thin async client over the Jira Cloud REST API v3.

Authentication is HTTP Basic with ``email:api_token`` (Atlassian's documented
scheme for Personal API Tokens). All methods raise ``JiraError`` with a
human-meaningful message so callers can surface clear errors to the user
instead of leaking raw upstream payloads.
"""
from __future__ import annotations

import urllib.parse

import httpx

_TIMEOUT = httpx.Timeout(15.0)

# Marker label stamped on every issue created through IdentityHub. It is how
# the "recent findings" view identifies app-created tickets — Jira is the sole
# source of truth, so this label *is* the query key (no local mirror table).
APP_LABEL = "identityhub"


class JiraError(Exception):
    """Raised for any Jira-side failure. ``status`` mirrors the upstream code
    where meaningful (401/403/404), or 502 for unexpected responses."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


class JiraClient:
    def __init__(self, site_url: str, email: str, api_token: str):
        # site_url is stored without scheme; Jira Cloud is always https.
        self._site_url = site_url
        self._base = f"https://{site_url}/rest/api/3"
        self._auth = (email, api_token)

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._base}{path}"
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.request(
                    method, url, auth=self._auth, **kwargs
                )
        except httpx.RequestError as exc:
            raise JiraError(
                f"Could not reach Jira at {self._base}. "
                "Check the site URL and your network.",
                status=502,
            ) from exc

        if resp.status_code in (401, 403):
            raise JiraError(
                "Jira rejected the credentials. Verify the email and API "
                "token, and that the token has not been revoked.",
                status=resp.status_code,
            )
        return resp

    async def verify(self) -> dict:
        """Confirm credentials work by fetching the current user."""
        resp = await self._request("GET", "/myself")
        if resp.status_code != 200:
            raise JiraError(
                "Unexpected response while verifying Jira credentials "
                f"(HTTP {resp.status_code}).",
                status=502,
            )
        return resp.json()

    async def list_projects(self) -> list[dict]:
        """Return projects visible to this user (first page, up to 50)."""
        resp = await self._request(
            "GET", "/project/search", params={"maxResults": 50, "orderBy": "name"}
        )
        if resp.status_code != 200:
            raise JiraError(
                f"Could not list Jira projects (HTTP {resp.status_code}).",
                status=502,
            )
        return resp.json().get("values", [])

    async def create_issue(
        self,
        project_key: str,
        summary: str,
        description: str,
        labels: list[str] | None = None,
        priority: str | None = None,
        extra_fields: dict | None = None,
    ) -> dict:
        """Create an Issue. Returns {key, url, labels}.

        The APP_LABEL marker is always added (and de-duplicated against any
        user labels). Issue type is fixed to "Task" (documented scope choice).
        ``priority`` is best-effort: many team-managed projects don't expose a
        priority field, in which case Jira returns a 400 we surface verbatim.

        Description uses the Atlassian Document Format (ADF) required by v3.
        """
        # Marker label first, then user labels, de-duplicated, order-preserving.
        all_labels = list(dict.fromkeys([APP_LABEL, *(labels or [])]))

        fields: dict = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": "Task"},
            "labels": all_labels,
            "description": _adf_from_text(description or "(no description)"),
        }
        if priority:
            fields["priority"] = {"name": priority}
        if extra_fields:
            # Pre-formatted Jira custom fields (keyed by customfield_XXXXX).
            fields.update(extra_fields)

        resp = await self._request("POST", "/issue", json={"fields": fields})

        if resp.status_code == 400:
            # Most commonly: bad project key, unsupported issue type, or a
            # field (e.g. priority) the project doesn't accept.
            detail = _extract_error(resp)
            raise JiraError(f"Jira rejected the issue: {detail}", status=400)
        if resp.status_code != 201:
            raise JiraError(
                f"Could not create Jira issue (HTTP {resp.status_code}).",
                status=502,
            )

        data = resp.json()
        key = data["key"]
        return {
            "key": key,
            "url": f"https://{self._site_url}/browse/{key}",
            "labels": all_labels,
        }

    async def add_remote_link(self, issue_key: str, url: str, title: str) -> None:
        """Attach a web link on the issue (Jira "remote link") pointing back to
        IdentityHub — the cross-reference that lets a user jump from the Jira
        ticket into the app. Best-effort: callers ignore failures so a link
        problem never blocks ticket creation."""
        payload = {"object": {"url": url, "title": title}}
        await self._request("POST", f"/issue/{issue_key}/remotelink", json=payload)

    async def search_app_issues(self, project_key: str, limit: int = 10) -> list[dict]:
        """Return the most recent IdentityHub-created issues for a project.

        Jira is the source of truth: we query by the APP_LABEL marker rather
        than a local table. Note Jira's search index is eventually consistent,
        so a just-created issue may take a moment to appear here.
        """
        jql = (
            f'project = "{project_key}" AND labels = "{APP_LABEL}" '
            f"ORDER BY created DESC"
        )
        params = {
            "jql": jql,
            "maxResults": str(limit),
            "fields": "summary,created,labels",
        }
        query = urllib.parse.urlencode(params)
        resp = await self._request("GET", f"/search/jql?{query}")

        if resp.status_code == 400:
            raise JiraError(
                f"Jira rejected the search: {_extract_error(resp)}", status=400
            )
        if resp.status_code != 200:
            raise JiraError(
                f"Could not search Jira issues (HTTP {resp.status_code}).",
                status=502,
            )

        issues = resp.json().get("issues", [])
        results = []
        for issue in issues:
            f = issue.get("fields", {})
            key = issue["key"]
            results.append(
                {
                    "key": key,
                    "url": f"https://{self._site_url}/browse/{key}",
                    "title": f.get("summary", ""),
                    "created": f.get("created"),
                    "labels": f.get("labels", []),
                }
            )
        return results


def _adf_from_text(text: str) -> dict:
    """Build an Atlassian Document Format doc from plain text, mapping each
    line to its own paragraph so multi-line descriptions render readably."""
    lines = text.split("\n")
    content = []
    for line in lines:
        para: dict = {"type": "paragraph", "content": []}
        if line:  # ADF paragraphs must omit empty text nodes
            para["content"].append({"type": "text", "text": line})
        content.append(para)
    return {"type": "doc", "version": 1, "content": content}


def _extract_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        messages = body.get("errorMessages") or []
        field_errors = body.get("errors") or {}
        parts = list(messages) + [f"{k}: {v}" for k, v in field_errors.items()]
        return "; ".join(parts) or "invalid request"
    except Exception:
        return "invalid request"
