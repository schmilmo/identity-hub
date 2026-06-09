"""Shared business logic for Jira connections and finding tickets, used by
both the UI router and the external REST API so the two stay consistent."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FindingTicket, JiraConnection, User
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


async def create_finding(
    db: AsyncSession,
    user: User,
    project_key: str,
    title: str,
    description: str,
    source: str,
) -> FindingTicket:
    """Create the Jira issue and persist a local record. Shared by UI + API."""
    conn = await get_connection_or_409(db, user)
    client = client_for(conn)

    try:
        result = await client.create_issue(project_key, title, description)
    except JiraError as exc:
        raise map_jira_error(exc) from exc

    ticket = FindingTicket(
        user_id=user.id,
        jira_project_key=project_key,
        jira_issue_key=result["key"],
        jira_issue_url=result["url"],
        title=title,
        source=source,
    )
    db.add(ticket)

    conn.last_verified_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ticket)
    return ticket


async def recent_findings(
    db: AsyncSession, user: User, project_key: str, limit: int = 10
) -> list[FindingTicket]:
    result = await db.execute(
        select(FindingTicket)
        .where(
            FindingTicket.user_id == user.id,
            FindingTicket.jira_project_key == project_key,
        )
        .order_by(FindingTicket.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
