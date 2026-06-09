"""External REST API (v1) for machine clients: scanners, CI/CD pipelines.

Differences from the UI-facing routes:
- Authenticated by API key (``Authorization: Bearer ih_live_...``), not a cookie.
- Versioned under /api/v1 so the contract can evolve without breaking clients.
- Documented status codes and validation errors for programmatic consumers.

Tenancy: the API key resolves to its owning user, and every created ticket is
scoped to that user — identical isolation to the UI path.
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import api_key_user
from app.models import User
from app.schemas import (
    CreateFindingRequest,
    ErrorResponse,
    FindingTicketResponse,
)
from app.services import findings_service

router = APIRouter(prefix="/api/v1", tags=["external-api"])


@router.post(
    "/findings",
    response_model=FindingTicketResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Finding ticket created in Jira."},
        400: {"model": ErrorResponse, "description": "Validation error or Jira rejected the issue."},
        401: {"model": ErrorResponse, "description": "Missing or invalid API key."},
        409: {"model": ErrorResponse, "description": "No Jira workspace connected for this account."},
        422: {"model": ErrorResponse, "description": "Request body failed schema validation."},
        502: {"model": ErrorResponse, "description": "Upstream Jira error."},
    },
)
async def create_finding(
    body: CreateFindingRequest,
    user: User = Depends(api_key_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an NHI finding ticket programmatically.

    Example:
        curl -X POST https://host/api/v1/findings \\
          -H "Authorization: Bearer ih_live_..." \\
          -H "Content-Type: application/json" \\
          -d '{"project_key":"NHI","title":"Stale SA: svc-deploy","description":"..."}'
    """
    ticket = await findings_service.create_finding(
        db, user, body.project_key, body.title, body.description, source="api"
    )
    return FindingTicketResponse(
        jira_issue_key=ticket.jira_issue_key,
        jira_issue_url=ticket.jira_issue_url,
        title=ticket.title,
        project_key=ticket.jira_project_key,
        source=ticket.source,
        created_at=ticket.created_at,
    )
