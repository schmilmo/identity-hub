"""Authentication routes: register, login, logout, current user.

Sessions are server-side. The cookie carries only an opaque id; logout and
expiry delete the row, revoking access immediately (unlike a stateless JWT).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import current_user
from app.models import JiraConnection, Session, User
from app.schemas import LoginRequest, RegisterRequest, UserResponse
from app.security.passwords import hash_password, verify_password
from app.security.tokens import generate_session_id

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# A precomputed argon2 hash used to equalize timing when the email is unknown,
# so login does not leak which emails are registered.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
    )


async def _create_session(db: AsyncSession, user_id: str) -> str:
    session_id = generate_session_id()
    expires = datetime.now(timezone.utc) + timedelta(
        seconds=settings.session_ttl_seconds
    )
    db.add(Session(id=session_id, user_id=user_id, expires_at=expires))
    await db.commit()
    return session_id


async def _to_user_response(db: AsyncSession, user: User) -> UserResponse:
    # Query explicitly rather than touching the lazy relationship, which
    # cannot be loaded outside the async greenlet context.
    result = await db.execute(
        select(JiraConnection.id).where(JiraConnection.user_id == user.id)
    )
    connected = result.scalar_one_or_none() is not None
    return UserResponse(id=user.id, email=user.email, jira_connected=connected)


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
async def register(
    body: RegisterRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)

    session_id = await _create_session(db, user.id)
    _set_session_cookie(response, session_id)
    return await _to_user_response(db, user)


@router.post("/login", response_model=UserResponse)
async def login(
    body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    # Always run a verify to keep timing uniform across known/unknown emails.
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    session_id = await _create_session(db, user.id)
    _set_session_cookie(response, session_id)
    return await _to_user_response(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        session = await db.get(Session, session_id)
        if session is not None:
            await db.delete(session)
            await db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    return await _to_user_response(db, user)
