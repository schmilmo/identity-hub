"""Server-side sessions, stored in Redis.

The cookie carries only an opaque session id; the Redis value maps it to a
user_id with a TTL, so Redis expires sessions automatically (no manual
``expires_at`` check or cleanup). Deleting the key revokes a session
immediately — the same semantics as the previous DB table, but out-of-process
(survives restarts, shared across workers/replicas).
"""
from app import redis_client
from app.security.tokens import generate_session_id

_PREFIX = "session:"


async def create(user_id: str, ttl_seconds: int) -> str:
    session_id = generate_session_id()
    await redis_client.get_redis().set(
        _PREFIX + session_id, user_id, ex=ttl_seconds
    )
    return session_id


async def get_user_id(session_id: str) -> str | None:
    return await redis_client.get_redis().get(_PREFIX + session_id)


async def delete(session_id: str) -> None:
    await redis_client.get_redis().delete(_PREFIX + session_id)
