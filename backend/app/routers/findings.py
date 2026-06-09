"""NHI finding tickets (UI-facing, session-authenticated)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models import FindingTicket, User
from app.schemas import CreateFindingRequest, FindingTicketResponse
from app.services import findings_service

router = APIRouter(prefix="/findings", tags=["findings"])


def _to_response(t: FindingTicket) -> FindingTicketResponse:
    return FindingTicketResponse(
        jira_issue_key=t.jira_issue_key,
        jira_issue_url=t.jira_issue_url,
        title=t.title,
        project_key=t.jira_project_key,
        source=t.source,
        created_at=t.created_at,
    )


@router.post("", response_model=FindingTicketResponse, status_code=201)
async def create_finding(
    body: CreateFindingRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await findings_service.create_finding(
        db, user, body.project_key, body.title, body.description, source="ui"
    )
    return _to_response(ticket)


@router.get("", response_model=list[FindingTicketResponse])
async def list_recent(
    project_key: str = Query(..., min_length=1),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """The 10 most recent tickets created from this app for the given project."""
    tickets = await findings_service.recent_findings(db, user, project_key, limit=10)
    return [_to_response(t) for t in tickets]
