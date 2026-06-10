# CLAUDE.md

Guidance for working in this repo. For *why* decisions were made, see `README.md`
(architecture, design decisions, security). This file is the operational map:
how it's wired, how to run/test, conventions, and gotchas.

## What this is
IdentityHub — a POC that reports Non-Human-Identity (NHI) findings to Jira, from a
web UI and a REST API. FastAPI + async SQLAlchemy + Postgres backend; React + Vite
+ TypeScript frontend; Redis for sessions; HashiCorp Vault (Transit) for credential
encryption; optional OIDC (Auth0) login.

## Run / build / test

```bash
# Full stack (Postgres + Redis + Vault + backend + frontend)
docker compose up --build          # UI :5173 · API :8000 (/docs) · Vault :8200

# Bonus digest worker, behind a profile (uses a free hosted LLM — set LLM_API_KEY):
docker compose --profile digest up --build

# Backend tests (SQLite + mocked Jira; no Postgres/Vault/network needed)
cd backend && .venv/bin/python -m pytest

# Frontend type-check + build
cd frontend && npm run build

# Backend alone (no Docker) — must opt out of Vault:
cd backend && CRYPTO_BACKEND=local OIDC_ISSUER="" \
  DATABASE_URL="sqlite+aiosqlite:///./dev.db" \
  APP_ENCRYPTION_KEY=dev uvicorn app.main:app --reload --port 8000
```

Local Python venv lives at `backend/.venv` (Python 3.13 locally; Docker pins 3.12).

## Layout
```
backend/app/
  main.py            # app wiring, CORS, SessionMiddleware (only if OIDC), lifespan
  config.py          # Settings (env). get_settings() is lru_cached.
  database.py        # async engine; init_db() = create_all (NO migrations)
  deps.py            # current_user (cookie→Redis) + api_key_user (Bearer) → User
  models.py          # users, jira_connections, api_keys, digest_subscriptions
                     #   (NO sessions table — Redis; NO findings table — Jira)
  session_store.py   # Redis-backed sessions; redis_client.py = the client
  schemas.py         # Pydantic request/response (decoupled from ORM)
  security/          # passwords (argon2), crypto (Vault/AES), tokens, oidc (Authlib)
  services/          # jira_client.py (thin async Jira REST), findings_service.py
  routers/           # auth, jira, findings, api_keys, digest, external_api (/api/v1)
  digest/            # bonus worker: blog.py (fetch), llm.py (OpenAI-compat
                     #   summarize), run.py (periodic loop). `python -m app.digest.run`
  tests/             # pytest; conftest.py has an in-memory fake Jira keyed by site
frontend/src/
  api/client.ts      # single typed backend boundary; ApiError + apiErrorMessage()
  auth/AuthContext   # session user; /auth/config drives login mode
  pages/ components/ # LoginPage, DashboardPage(=Report tab), FindingsListPage,
                     #   FindingDetailPage, ApiKeysPage + presentational parts
```

## Architecture essentials
- **Layering:** routers (HTTP only) → services (shared business logic) → jira_client
  / security. `findings_service.create_finding()` is the single path used by BOTH
  the UI router and `/api/v1`, so they can't drift.
- **Three-layer identity:** app login (session cookie) ≠ Jira connection (encrypted
  token) ≠ IdentityHub API keys (hashed). Linked by one `user_id`.
- **Multi-tenancy = scope by `user_id`** (the tenant key), resolved in `deps.py`.
  Every tenant-scoped query filters on it. 1 user = 1 tenant for now.
- **Jira is the source of truth for tickets** — no local ticket table. The "recent"
  view is a JQL search on the `identityhub` marker label.
- **Sessions live in Redis** (opaque id → user_id, TTL = session lifetime), not the
  DB. Out-of-process so they survive restarts and work across workers/replicas.
  `app/session_store.py` is the seam; logout deletes the key.

## Key configurable behaviors (env)
- `CRYPTO_BACKEND` = `vault` (default) | `local`. Vault Transit encrypts Jira
  tokens; key never leaves Vault; DB stores `vault:v1:…`. `local` = AES-256-GCM
  with `APP_ENCRYPTION_KEY`. Tests pin `local`.
- **OIDC**: set `OIDC_ISSUER`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET` → SSO login
  (password endpoints return 403). Unset → email+password. `/auth/config` tells the
  frontend which to show.
- `NHI_FIELD_MAP` (JSON) maps NHI context fields → Jira custom-field ids+types;
  unmapped fields fall back to the description. Empty = all in description.
- On create, a Jira **remote link** ("View in IdentityHub", `?project=KEY`) is added
  best-effort (cross-reference back to the app).

## Conventions
- **Errors:** every API error is `{"detail": "<message>"}`; 422 validation is
  flattened to one readable line (`main.py` handler). Upstream Jira errors are
  translated, never leaked raw (Jira 401/403 → our 502 + reconnect hint; Jira 400 →
  our 400 passthrough). Frontend uses `apiErrorMessage(err, fallback)` —
  **never `instanceof ApiError`** (unreliable under Vite HMR).
- **Async SQLAlchemy:** don't touch lazy relationships outside the greenlet —
  query explicitly (see `_to_user_response`, the connect handler). Normalize naive
  datetimes to UTC before comparing (SQLite returns naive).
- **Secrets:** never store plaintext — passwords argon2-hashed, API keys
  sha256-hashed (shown once), Jira tokens encrypted. `.env` is gitignored.
- **Cross-tenant access** returns `404`, not `403` (don't leak existence).

## Gotchas (these have bitten us)
- **No migrations.** `init_db()` uses `create_all`, which CREATES missing tables
  but never ALTERS/DROPS. After any model/schema change, reset the DB:
  `docker compose down -v && docker compose up`. (Production → Alembic.)
- **Env changes need recreate, not restart.** Editing `.env` → `docker compose up -d
  <service>` (re-reads .env). `docker compose restart` / `docker restart` keep the
  OLD env. Also `get_settings()` is cached per process, so config is read once at
  boot.
- **Vault dev mode is in-memory** — restarting the vault container loses the Transit
  key, making stored tokens undecryptable (demo-only).
- **SSO mode hides the password flow** — `/auth/register` & `/auth/login` return 403;
  the UI shows the SSO button. To exercise password paths, run with `OIDC_*` unset.
- **Team-managed Jira projects** (e.g. SAM1): `createmeta` is unreliable (won't list
  custom fields that are still settable); the global field API can't rename/manage
  their project-scoped custom fields (404). Verify by actually creating an issue.
- **Frontend container runs the Vite dev server** (`npm run dev`), not a prod build.

## Testing
- `backend/tests/conftest.py` swaps the Jira client for an in-memory fake keyed by
  `site_url` (so two users on different Jira sites are isolated), backs sessions
  with **fakeredis**, and pins SQLite + `CRYPTO_BACKEND=local`. No network,
  Postgres, Redis, or Vault required.
- Cover the contract you change: status codes, tenant isolation, error messages.

## Conventions for changes
- Keep `README.md` current with every change (it's the graded living doc). Record
  decisions + rationale in the relevant **Design decisions** subsection — there is
  no standalone "Decision log" (removed deliberately).
- End git commit messages with the `Co-Authored-By: Claude …` trailer.

## Bonus: NHI Blog Digest
- `app/digest/` — periodic worker (separate container, shared code). Fetch latest
  oasis.security/blog post → summarize once via a **free, provider-agnostic LLM**
  (OpenAI-compatible `chat/completions`; default = Groq free tier, set
  `LLM_API_KEY`; override `LLM_BASE_URL`/`LLM_MODEL` for Gemini/OpenRouter/Ollama)
  → file a ticket
  for each **per-user subscription** (`digest_subscriptions`, set in UI: Report →
  NHI Blog Digest) under **that user's own** Jira connection. Dedup per
  (user, project) in Redis.
- No Anthropic/paid SDK. Don't invoke the claude-api skill here.
- Runs behind the `digest` Compose profile (so default `up` stays lean).
