"""Jira connection management (UI-facing, session-authenticated)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models import JiraConnection, User
from app.schemas import (
    JiraConnectionResponse,
    JiraConnectRequest,
    JiraProject,
)
from app.security.crypto import encrypt
from app.services.findings_service import (
    client_for,
    get_connection_or_409,
    map_jira_error,
)
from app.services.jira_client import JiraClient, JiraError

router = APIRouter(prefix="/jira", tags=["jira"])


@router.post("/connect", response_model=JiraConnectionResponse)
async def connect(
    body: JiraConnectRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify the supplied credentials against Jira, then store the token
    encrypted. We never persist an unverified or invalid credential."""
    client = JiraClient(body.site_url, body.jira_email, body.api_token)
    try:
        await client.verify()
    except JiraError as exc:
        raise map_jira_error(exc) from exc

    ciphertext, nonce = encrypt(body.api_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(JiraConnection).where(JiraConnection.user_id == user.id)
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.site_url = body.site_url
        existing.jira_email = body.jira_email
        existing.api_token_ciphertext = ciphertext
        existing.api_token_nonce = nonce
        existing.last_verified_at = now
        conn = existing
    else:
        conn = JiraConnection(
            user_id=user.id,
            site_url=body.site_url,
            jira_email=body.jira_email,
            api_token_ciphertext=ciphertext,
            api_token_nonce=nonce,
            last_verified_at=now,
        )
        db.add(conn)

    await db.commit()
    await db.refresh(conn)
    return JiraConnectionResponse(
        site_url=conn.site_url,
        jira_email=conn.jira_email,
        connected_at=conn.connected_at,
        last_verified_at=conn.last_verified_at,
    )


@router.get("/connection", response_model=JiraConnectionResponse)
async def get_connection(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    conn = await get_connection_or_409(db, user)
    return JiraConnectionResponse(
        site_url=conn.site_url,
        jira_email=conn.jira_email,
        connected_at=conn.connected_at,
        last_verified_at=conn.last_verified_at,
    )


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    conn = await get_connection_or_409(db, user)
    await db.delete(conn)
    await db.commit()


@router.get("/projects", response_model=list[JiraProject])
async def list_projects(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    conn = await get_connection_or_409(db, user)
    client = client_for(conn)
    try:
        projects = await client.list_projects()
    except JiraError as exc:
        raise map_jira_error(exc) from exc
    return [JiraProject(key=p["key"], name=p["name"]) for p in projects]
