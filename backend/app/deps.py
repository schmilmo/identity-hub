"""Shared FastAPI dependencies for authentication.

Two distinct auth schemes, never mixed:
- ``current_user`` — browser sessions (cookie), used by the UI-facing API.
- ``api_key_user`` — Bearer API key, used by the external /api/v1 API.

Both resolve to a User and scope every downstream query by user_id, which is
the tenant boundary for this POC.
"""
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import ApiKey, Session, User
from app.security.tokens import hash_api_key

settings = get_settings()


async def current_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """Resolve the logged-in user from the session cookie."""
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )

    session = await db.get(Session, session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session"
        )

    # SQLite returns naive datetimes; normalize to UTC before comparing.
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        await db.delete(session)
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired"
        )

    user = await db.get(User, session.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session"
        )
    return user


async def api_key_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the owning user from an ``Authorization: Bearer <key>`` header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header. "
            "Expected 'Bearer <api_key>'.",
        )

    presented = authorization.removeprefix("Bearer ").strip()
    key_hash = hash_api_key(presented)

    result = await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    api_key = result.scalar_one_or_none()

    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )

    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    user = await db.get(User, api_key.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    return user
