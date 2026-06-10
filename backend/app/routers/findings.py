"""NHI finding tickets (UI-facing, session-authenticated).

Tickets live in Jira (source of truth); this router has no local store.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models import User
from app.schemas import (
    CreateFindingRequest,
    FindingDetailResponse,
    FindingTicketResponse,
)
from app.services import findings_service

router = APIRouter(prefix="/findings", tags=["findings"])


@router.post("", response_model=FindingTicketResponse, status_code=201)
async def create_finding(
    body: CreateFindingRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await findings_service.create_finding(db, user, body)
    return FindingTicketResponse(**result)


@router.get("", response_model=list[FindingTicketResponse])
async def list_findings(
    project_key: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """App-created tickets read live from Jira via the IdentityHub marker label.
    Omit ``project_key`` to list across all projects the account can see."""
    results = await findings_service.list_findings(db, user, project_key, limit=limit)
    return [FindingTicketResponse(**r) for r in results]


@router.get("/{issue_key}", response_model=FindingDetailResponse)
async def get_finding(
    issue_key: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full detail for one finding, reconstructed from Jira for the in-app page."""
    result = await findings_service.get_finding(db, user, issue_key)
    return FindingDetailResponse(**result)
