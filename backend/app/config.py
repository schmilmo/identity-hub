"""Application configuration, loaded from environment variables.

Secrets (encryption key, DB URL) live in the environment, never in the
database or source. See .env.example for the full list.
"""
import json
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

    # Session lifetime in seconds (default 7 days). Used as the Redis key TTL.
    session_ttl_seconds: int = 60 * 60 * 24 * 7

    # Redis — out-of-process session store (opaque session id → user_id, TTL'd).
    redis_url: str = "redis://redis:6379/0"

    # Cookie settings. secure_cookies should be True behind HTTPS in prod.
    secure_cookies: bool = False
    session_cookie_name: str = "ih_session"

    # Anthropic key for the NHI Blog Digest bonus (optional for core app).
    anthropic_api_key: str = ""

    # CORS origin for the frontend dev server.
    frontend_origin: str = "http://localhost:5173"

    # --- Credential encryption backend ---
    # "vault"  -> HashiCorp Vault Transit (default): the key never leaves Vault.
    # "local"  -> AES-256-GCM with app_encryption_key (no external dependency;
    #             used by the test suite and for Vault-free local runs).
    crypto_backend: str = "vault"

    # Vault Transit settings (used when crypto_backend == "vault").
    vault_addr: str = "http://vault:8200"
    vault_token: str = "root"  # dev-mode root token; use AppRole/etc. in prod
    vault_transit_mount: str = "transit"
    vault_transit_key: str = "identityhub"

    # --- OIDC / hosted IdP login (e.g. Auth0) ---
    # When all three of issuer/client_id/client_secret are set, the app uses
    # OIDC login (Authorization Code + PKCE). Otherwise it falls back to local
    # email+password auth, so the default `docker compose up` and tests still
    # work with no external IdP.
    oidc_issuer: str = ""  # e.g. https://your-tenant.us.auth0.com
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/auth/oidc/callback"
    oidc_scopes: str = "openid email profile"
    # Where to send the browser after login/logout (the frontend).
    oidc_post_login_redirect: str = "http://localhost:5173/"
    # Secret for the short-lived signed cookie holding OAuth state/nonce/PKCE.
    oidc_state_secret: str = "dev-only-oidc-state-secret-change-me"

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_client_id and self.oidc_client_secret)

    # --- NHI context → Jira custom-field mapping (optional) ---
    # Deployment-level JSON mapping each NHI context field to a Jira custom
    # field id + type, e.g.:
    #   NHI_FIELD_MAP='{"resource":{"id":"customfield_10042","type":"text"},
    #                   "last_activity":{"id":"customfield_10045","type":"date"}}'
    # Unmapped fields fall back to the description template. Empty = all in
    # the description (the portable default).
    nhi_field_map: str = ""

    def field_map(self) -> dict[str, dict]:
        """Parsed NHI_FIELD_MAP; returns {} if unset or malformed (fail soft —
        a bad mapping degrades to the description rather than breaking creates)."""
        raw = self.nhi_field_map.strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
