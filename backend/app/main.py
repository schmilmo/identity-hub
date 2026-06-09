"""FastAPI application entrypoint.

Route layout:
  /auth/*        session-authenticated auth (register/login/logout/me)
  /jira/*        session-authenticated Jira connection management
  /findings/*    session-authenticated finding tickets (UI)
  /api-keys/*    session-authenticated API key management (UI)
  /api/v1/*      API-key-authenticated external API (machines)
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.database import init_db
from app.routers import api_keys, auth, external_api, findings, jira
from app.security import crypto

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    crypto.ensure_ready()  # Vault backend: ensure transit engine + key exist
    yield


app = FastAPI(title="IdentityHub", version="1.0.0", lifespan=lifespan)

# CORS for the React dev server. allow_credentials=True so the session cookie
# is sent; origin is restricted (cannot use "*" with credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Authlib stores the short-lived OAuth state/nonce/PKCE verifier in a signed
# session cookie during the redirect dance. Only needed when OIDC is enabled.
if settings.oidc_enabled:
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.oidc_state_secret,
        same_site="lax",
        https_only=settings.secure_cookies,
    )


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    """Return a single readable message for schema validation failures so
    both humans and machine clients get a clear, consistent error shape."""
    first = exc.errors()[0] if exc.errors() else None
    if first:
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = f"{loc}: {first.get('msg')}" if loc else first.get("msg", "Invalid request")
    else:
        msg = "Invalid request"
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": msg}
    )


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(jira.router)
app.include_router(findings.router)
app.include_router(api_keys.router)
app.include_router(external_api.router)
