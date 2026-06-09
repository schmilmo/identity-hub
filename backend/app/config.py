"""Application configuration, loaded from environment variables.

Secrets (encryption key, DB URL) live in the environment, never in the
database or source. See .env.example for the full list.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres connection (async driver)
    database_url: str = "postgresql+asyncpg://identityhub:identityhub@db:5432/identityhub"

    # 32-byte (256-bit) key, base64- or hex-encoded, used to AES-GCM encrypt
    # Jira API tokens at rest. MUST be set to a stable value in production;
    # rotating it makes existing stored tokens undecryptable.
    app_encryption_key: str = "dev-only-insecure-key-change-me-32bytes!!"

    # Session lifetime in seconds (default 7 days).
    session_ttl_seconds: int = 60 * 60 * 24 * 7

    # Cookie settings. secure_cookies should be True behind HTTPS in prod.
    secure_cookies: bool = False
    session_cookie_name: str = "ih_session"

    # Anthropic key for the NHI Blog Digest bonus (optional for core app).
    anthropic_api_key: str = ""

    # CORS origin for the frontend dev server.
    frontend_origin: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
