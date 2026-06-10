"""NHI Blog Digest subscriptions (UI-facing, session-authenticated).

A user chooses which Jira project(s) the digest should file tickets in. The
digest worker (app/digest/run.py) reads these and files under each user's own
Jira connection.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models import DigestSubscription, User
from app.schemas import (
    DigestSubscriptionsResponse,
    UpdateDigestSubscriptionsRequest,
)

router = APIRouter(prefix="/digest", tags=["digest"])


@router.get("/subscriptions", response_model=DigestSubscriptionsResponse)
async def get_subscriptions(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(DigestSubscription.project_key).where(
            DigestSubscription.user_id == user.id
        )
    )
    return DigestSubscriptionsResponse(project_keys=list(result.scalars().all()))


@router.put("/subscriptions", response_model=DigestSubscriptionsResponse)
async def set_subscriptions(
    body: UpdateDigestSubscriptionsRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the user's subscriptions with the given set of project keys."""
    result = await db.execute(
        select(DigestSubscription).where(DigestSubscription.user_id == user.id)
    )
    existing = {s.project_key: s for s in result.scalars().all()}
    wanted = set(body.project_keys)

    for key, sub in existing.items():
        if key not in wanted:
            await db.delete(sub)
    for key in wanted - existing.keys():
        db.add(DigestSubscription(user_id=user.id, project_key=key))

    await db.commit()
    return DigestSubscriptionsResponse(project_keys=sorted(wanted))
