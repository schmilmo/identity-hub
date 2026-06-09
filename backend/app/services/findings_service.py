"""Shared business logic for Jira connections and finding tickets, used by
both the UI router and the external REST API so the two stay consistent.

Jira is the single source of truth for finding tickets: we create issues there
(stamped with the APP_LABEL marker) and read the "recent" list back via search.
There is no local mirror of tickets.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import JiraConnection, User
from app.schemas import CreateFindingRequest
from app.security.crypto import decrypt
from app.services.jira_client import JiraClient, JiraError


async def get_connection_or_409(db: AsyncSession, user: User) -> JiraConnection:
    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user.id)
    )
    conn = result.scalar_one_or_none()
    if conn is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No Jira workspace connected. Connect Jira before creating tickets.",
        )
    return conn


def client_for(conn: JiraConnection) -> JiraClient:
    token = decrypt(conn.api_token_ciphertext, conn.api_token_nonce)
    return JiraClient(conn.site_url, conn.jira_email, token)


def map_jira_error(exc: JiraError) -> HTTPException:
    """Translate an upstream Jira failure into an appropriate client-facing
    HTTP error. 401/403 from Jira become 502 to us (our stored creds are bad),
    surfaced with a clear reconnect message; 400 stays a 400 (caller's input)."""
    if exc.status == 400:
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)
    if exc.status in (401, 403):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.message + " You may need to reconnect Jira.",
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message)


def _compose_description(req: CreateFindingRequest) -> str:
    """Fold the free-text description and the NHI-specific context fields into a
    single structured description. These fields have no portable native Jira
    mapping, so we render them as a readable block instead."""
    parts: list[str] = []
    if req.description and req.description.strip():
        parts.append(req.description.strip())

    context = [
        ("Affected resource", req.resource),
        ("Finding category", req.category),
        ("Environment", req.environment),
        ("Last activity", req.last_activity),
    ]
    context_lines = [f"- {label}: {value}" for label, value in context if value]
    if context_lines:
        if parts:
            parts.append("")  # blank line between description and the block
        parts.append("NHI Finding Details:")
        parts.extend(context_lines)

    return "\n".join(parts) if parts else "(no description)"


async def create_finding(
    db: AsyncSession, user: User, req: CreateFindingRequest
) -> dict:
    """Create the Jira issue. Returns the created issue's key/url/labels.
    No local persistence — Jira owns the record."""
    conn = await get_connection_or_409(db, user)
    client = client_for(conn)

    try:
        result = await client.create_issue(
            project_key=req.project_key,
            summary=req.title,
            description=_compose_description(req),
            labels=req.labels,
            priority=req.priority,
            due_date=req.due_date.isoformat() if req.due_date else None,
        )
    except JiraError as exc:
        raise map_jira_error(exc) from exc

    # Refresh the connection's "last verified" stamp on a successful call.
    conn.last_verified_at = datetime.now(timezone.utc)
    await db.commit()

    return {
        "jira_issue_key": result["key"],
        "jira_issue_url": result["url"],
        "title": req.title,
        "project_key": req.project_key,
        "labels": result["labels"],
        # Server time; the authoritative timestamp is Jira's, seen on next refresh.
        "created_at": datetime.now(timezone.utc),
    }


async def recent_findings(
    db: AsyncSession, user: User, project_key: str, limit: int = 10
) -> list[dict]:
    """The most recent IdentityHub-created issues for a project, read from Jira."""
    conn = await get_connection_or_409(db, user)
    client = client_for(conn)

    try:
        issues = await client.search_app_issues(project_key, limit=limit)
    except JiraError as exc:
        raise map_jira_error(exc) from exc

    return [
        {
            "jira_issue_key": i["key"],
            "jira_issue_url": i["url"],
            "title": i["title"],
            "project_key": project_key,
            "labels": i["labels"],
            "created_at": i["created"],  # ISO string; pydantic coerces to datetime
        }
        for i in issues
    ]
