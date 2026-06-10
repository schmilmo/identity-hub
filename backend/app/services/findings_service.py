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

from app.config import get_settings
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


# NHI context fields, with the label used in the description block.
_NHI_CONTEXT = [
    ("resource", "Affected resource"),
    ("category", "Finding category"),
    ("environment", "Environment"),
    ("last_activity", "Last activity"),
]


def _format_custom_value(field_type: str, value):
    """Shape a value for Jira per the mapped custom-field type."""
    if field_type == "option":
        return {"value": value}
    if field_type == "array":
        values = value if isinstance(value, list) else [value]
        return [{"value": v} for v in values]
    # text, date, and anything else: send the scalar as-is.
    return value


def build_custom_fields(
    req: CreateFindingRequest, field_map: dict[str, dict]
) -> tuple[dict, set[str]]:
    """From the NHI_FIELD_MAP, build the Jira `fields` fragment for any NHI
    context value that has a mapping. Returns (extra_fields, mapped_keys) so the
    description can skip whatever was sent as a real field."""
    values = {key: getattr(req, key) for key, _ in _NHI_CONTEXT}
    extra: dict = {}
    mapped: set[str] = set()
    for key, spec in field_map.items():
        value = values.get(key)
        cf_id = (spec or {}).get("id")
        if not value or not cf_id:
            continue
        extra[cf_id] = _format_custom_value(spec.get("type", "text"), value)
        mapped.add(key)
    return extra, mapped


def _compose_description(req: CreateFindingRequest, exclude: set[str]) -> str:
    """Fold the free-text description and the *unmapped* NHI context fields into
    a single structured description. Fields sent as real custom fields (in
    `exclude`) are omitted here to avoid duplication."""
    parts: list[str] = []
    if req.description and req.description.strip():
        parts.append(req.description.strip())

    context_lines = [
        f"- {label}: {getattr(req, key)}"
        for key, label in _NHI_CONTEXT
        if getattr(req, key) and key not in exclude
    ]
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

    # Map NHI context to Jira custom fields where configured; the rest goes into
    # the description (the portable default).
    extra_fields, mapped = build_custom_fields(req, get_settings().field_map())

    try:
        result = await client.create_issue(
            project_key=req.project_key,
            summary=req.title,
            description=_compose_description(req, exclude=mapped),
            labels=req.labels,
            priority=req.priority,
            extra_fields=extra_fields or None,
        )
    except JiraError as exc:
        raise map_jira_error(exc) from exc

    # Cross-reference: add a web link on the Jira issue back to IdentityHub so a
    # user can jump from the ticket into the app (deep-linked to the project).
    # Best-effort — a link failure must not undo a successfully created ticket.
    settings = get_settings()
    app_url = f"{settings.frontend_origin.rstrip('/')}/?project={req.project_key}"
    try:
        await client.add_remote_link(result["key"], app_url, "View in IdentityHub")
    except JiraError:
        pass

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


async def list_findings(
    db: AsyncSession, user: User, project_key: str | None = None, limit: int = 10
) -> list[dict]:
    """IdentityHub-created issues read from Jira. ``project_key=None`` lists
    across all projects the account can see."""
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
            # Prefer the project from Jira; fall back to the requested one.
            "project_key": i.get("project_key") or project_key or "",
            "labels": i["labels"],
            "created_at": i["created"],  # ISO string; pydantic coerces to datetime
        }
        for i in issues
    ]


async def get_finding(db: AsyncSession, user: User, issue_key: str) -> dict:
    """Full detail for one finding, reconstructed from Jira (the source of
    truth). Maps any configured custom fields back to NHI context names."""
    conn = await get_connection_or_409(db, user)
    client = client_for(conn)

    field_map = get_settings().field_map()
    # nhi field name -> customfield id, and the reverse for reading back.
    id_by_nhi = {k: v.get("id") for k, v in field_map.items() if v.get("id")}
    extra_ids = list(id_by_nhi.values())

    try:
        issue = await client.get_issue(issue_key, extra_ids)
    except JiraError as exc:
        raise map_jira_error(exc) from exc

    # Pull NHI context out of custom fields where mapped (value shape varies).
    def _scalar(v):
        if isinstance(v, dict):
            return v.get("value") or v.get("name")
        return v

    custom = issue["custom_fields"]
    context = {
        nhi: _scalar(custom.get(cf_id)) for nhi, cf_id in id_by_nhi.items()
    }

    return {
        "jira_issue_key": issue["key"],
        "jira_issue_url": issue["url"],
        "title": issue["title"],
        "description": issue["description"],
        "labels": issue["labels"],
        "priority": issue["priority"],
        "status": issue["status"],
        "assignee": issue["assignee"],
        "created_at": issue["created"],
        "resource": context.get("resource"),
        "category": context.get("category"),
        "environment": context.get("environment"),
        "last_activity": context.get("last_activity"),
    }
