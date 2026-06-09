"""IdentityHub API key management (UI-facing, session-authenticated).

These keys authenticate *external systems* to our /api/v1 endpoints. The
plaintext is returned exactly once, at creation; thereafter only a hash and a
display prefix exist."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.models import ApiKey, User
from app.schemas import (
    ApiKeyResponse,
    CreateApiKeyRequest,
    CreateApiKeyResponse,
)
from app.security.tokens import (
    generate_api_key,
    hash_api_key,
    key_prefix_for_display,
)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


def _to_response(k: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=k.id,
        name=k.name,
        key_prefix=k.key_prefix,
        created_at=k.created_at,
        last_used_at=k.last_used_at,
        revoked_at=k.revoked_at,
    )


@router.post("", response_model=CreateApiKeyResponse, status_code=201)
async def create_key(
    body: CreateApiKeyRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    plaintext = generate_api_key()
    key = ApiKey(
        user_id=user.id,
        name=body.name,
        key_hash=hash_api_key(plaintext),
        key_prefix=key_prefix_for_display(plaintext),
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    resp = _to_response(key)
    return CreateApiKeyResponse(**resp.model_dump(), api_key=plaintext)


@router.get("", response_model=list[ApiKeyResponse])
async def list_keys(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    )
    return [_to_response(k) for k in result.scalars().all()]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    key = await db.get(ApiKey, key_id)
    # Scope to the owner: never reveal or mutate another tenant's key.
    if key is None or key.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found."
        )
    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await db.commit()
