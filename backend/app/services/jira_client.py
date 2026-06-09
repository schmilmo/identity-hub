"""Thin async client over the Jira Cloud REST API v3.

Authentication is HTTP Basic with ``email:api_token`` (Atlassian's documented
scheme for Personal API Tokens). All methods raise ``JiraError`` with a
human-meaningful message so callers can surface clear errors to the user
instead of leaking raw upstream payloads.
"""
from __future__ import annotations

import httpx

_TIMEOUT = httpx.Timeout(15.0)


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
        self, project_key: str, summary: str, description: str
    ) -> dict:
        """Create an Issue. Returns {key, url}. We add an 'identityhub' label
        so tickets are identifiable inside Jira as well as in our local store.

        Description uses the Atlassian Document Format (ADF) required by v3.
        """
        payload = {
            "fields": {
                "project": {"key": project_key},
                "summary": summary,
                "issuetype": {"name": "Task"},
                "labels": ["identityhub", "nhi-finding"],
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": description or "(no description)"}
                            ],
                        }
                    ],
                },
            }
        }
        resp = await self._request("POST", "/issue", json=payload)

        if resp.status_code == 400:
            # Most commonly: bad project key or issue type not available.
            detail = _extract_error(resp)
            raise JiraError(
                f"Jira rejected the issue: {detail}", status=400
            )
        if resp.status_code != 201:
            raise JiraError(
                f"Could not create Jira issue (HTTP {resp.status_code}).",
                status=502,
            )

        data = resp.json()
        key = data["key"]
        return {"key": key, "url": f"https://{self._site_url}/browse/{key}"}


def _extract_error(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        messages = body.get("errorMessages") or []
        field_errors = body.get("errors") or {}
        parts = list(messages) + [f"{k}: {v}" for k, v in field_errors.items()]
        return "; ".join(parts) or "invalid request"
    except Exception:
        return "invalid request"
