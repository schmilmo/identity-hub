"""Lazily-created async Redis client (shared singleton).

Kept tiny and importable so tests can swap ``_client`` for a fake before the
app touches Redis.
"""
import redis.asyncio as redis

from app.config import get_settings

_client: "redis.Redis | None" = None


def get_redis() -> "redis.Redis":
    global _client
    if _client is None:
        _client = redis.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _client
