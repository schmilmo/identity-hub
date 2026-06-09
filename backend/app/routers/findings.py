"""NHI finding tickets (UI-facing, session-authenticated).

Tickets live in Jira (source of truth); this router has no local store.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models import User
from app.schemas import CreateFindingRequest, FindingTicketResponse
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
async def list_recent(
    project_key: str = Query(..., min_length=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """The 10 most recent tickets created from this app for the given project,
    read live from Jira via the IdentityHub marker label."""
    results = await findings_service.recent_findings(db, user, project_key, limit=10)
    return [FindingTicketResponse(**r) for r in results]
