"""OIDC client (provider-agnostic) built on Authlib.

When ``oidc_enabled`` is true (issuer + client id + secret configured), the app
authenticates users against a hosted IdP (e.g. Auth0) using the Authorization
Code flow with PKCE, discovering endpoints from the provider's
``/.well-known/openid-configuration``. The client is built lazily so Authlib is
only exercised when OIDC is actually configured.
"""
from authlib.integrations.starlette_client import OAuth

from app.config import get_settings

_oauth: OAuth | None = None
PROVIDER_NAME = "idp"


def get_oauth() -> OAuth:
    global _oauth
    if _oauth is None:
        s = get_settings()
        oauth = OAuth()
        oauth.register(
            name=PROVIDER_NAME,
            server_metadata_url=(
                f"{s.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
            ),
            client_id=s.oidc_client_id,
            client_secret=s.oidc_client_secret,
            client_kwargs={"scope": s.oidc_scopes},
        )
        _oauth = oauth
    return _oauth


def provider():
    """The registered OAuth remote app for the IdP."""
    return getattr(get_oauth(), PROVIDER_NAME)
