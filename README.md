# IdentityHub — Jira NHI Finding Integration (POC)

A proof-of-concept integration that lets IdentityHub users report Non-Human
Identity (NHI) findings — stale service accounts, overprivileged keys, expiring
credentials — as Jira tickets, both from a web UI and programmatically from
external systems (scanners, CI/CD).

> Built as a take-home exercise. The emphasis is on **clean UI/backend
> separation, secure multi-tenant credential handling, and documented design
> decisions** — see [Design Decisions](#design-decisions) for the reasoning
> behind every significant choice.

---

## Table of contents

- [What it does](#what-it-does)
- [Setup](#setup)
- [Using the web app](#using-the-web-app)
- [Architecture](#architecture)
- [The three-layer identity model](#the-three-layer-identity-model)
- [Data model](#data-model)
- [Design decisions](#design-decisions)
  - [Why not the `jira` Python package?](#why-not-the-jira-python-package)
- [Security practices](#security-practices)
- [API reference](#api-reference)
- [Assumptions & scope](#assumptions--scope)
- [Decision log](#decision-log)

---

## What it does

| Requirement | Status | Where |
|---|---|---|
| App login / logout, secure server-side sessions | ✅ | `app/routers/auth.py` |
| Multi-tenant isolation (no cross-user data leakage) | ✅ | `app/deps.py`, every query scoped by `user_id` |
| Connect a Jira workspace (credentials encrypted at rest) | ✅ | `app/routers/jira.py` |
| Create an NHI finding ticket (project + title + description) | ✅ | `app/routers/findings.py` |
| Recent tickets view (10 most recent created via this app, per project) | ✅ | `app/routers/findings.py` |
| External REST API with API-key auth, validation, status codes | ✅ | `app/routers/external_api.py` |
| Web UI (login, Jira connect, create finding, recent tickets, API keys) | ✅ | `frontend/` (React + Vite + TS) |
| Bonus: NHI Blog Digest automation | ⏳ planned | `digest/` |

## Setup

### Prerequisites
- **Docker + Docker Compose** (the recommended path — nothing else to install).
- A free **Jira Cloud** account (atlassian.com) and a **Personal API Token**
  from <https://id.atlassian.com/manage-profile/security/api-tokens>.

### Run everything with Docker Compose (recommended)

```bash
# 1. (Optional) set a strong encryption key. A weak dev default is used if you skip this.
cp .env.example .env
#    then edit .env and set APP_ENCRYPTION_KEY to a 32-byte secret, e.g.:
#    python -c 'import secrets;print(secrets.token_urlsafe(32))'

# 2. Build and start the stack (Postgres + backend + frontend).
docker compose up --build
```

That's it. Three services start:

| URL | What |
|---|---|
| <http://localhost:5173> | **Web app** — open this to use IdentityHub |
| <http://localhost:8000/docs> | Interactive API docs (OpenAPI/Swagger) |
| <http://localhost:8000/health> | Health check |

Stop with `Ctrl-C`, or `docker compose down` (add `-v` to also wipe the
Postgres volume and start fresh).

### Configuration

All configuration is via environment variables (read from `.env` by Compose).

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENCRYPTION_KEY` | weak dev placeholder | Master key for Jira-token encryption. **Set a stable 32-byte secret for any real use** — rotating it makes stored tokens undecryptable. |
| `DATABASE_URL` | Compose Postgres | Async SQLAlchemy connection string |
| `SESSION_TTL_SECONDS` | `604800` (7d) | Session lifetime |
| `SECURE_COOKIES` | `false` | Set `true` behind HTTPS in production |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS origin allowed to send the session cookie |
| `ANTHROPIC_API_KEY` | — | For the bonus NHI Blog Digest |
| `DIGEST_USER_EMAIL` / `DIGEST_PROJECT_KEY` | — | Target account + project for the bonus digest |

---

## Using the web app

Open <http://localhost:5173>.

1. **Create an account.** On the landing screen choose **Create account**, enter
   an email and a password (min 8 chars), and submit. You're logged straight in.
   (Returning users use **Log in**.) Sessions are cookie-based and survive a
   page refresh; **Log out** is in the top-right.

2. **Connect your Jira workspace.** On the dashboard, the **Connect Jira** panel
   asks for three things:
   - **Site URL** — your Jira host, e.g. `your-site.atlassian.net` (with or
     without `https://`).
   - **Jira email** — the account the API token belongs to.
   - **API token** — a Personal API Token from
     [id.atlassian.com](https://id.atlassian.com/manage-profile/security/api-tokens).

   The credentials are **verified against Jira before anything is stored**, and
   the token is encrypted at rest. On success the panel flips to a "Connected"
   summary with a **Disconnect** option. If Jira rejects the credentials you get
   a clear message explaining what to fix.

3. **Report an NHI finding.** In **New NHI finding**:
   - **Project** — pick one of your workspace projects from the dropdown, or
     just type a project key (e.g. `NHI`).
   - **Title** — the summary, e.g. `Stale Service Account: svc-deploy-prod`.
   - **Description** — details about the finding (optional).

   Submit to create the Jira issue. A confirmation shows the new issue key
   (e.g. `NHI-42`). The issue is also tagged in Jira with the `identityhub` and
   `nhi-finding` labels.

4. **Review recent findings.** The **Recent findings** panel lists the 10 most
   recent tickets *created through IdentityHub* for the selected project,
   newest first, with their creation time. Click any row to open the issue in
   Jira in a new tab. Tickets created by an external system via the API are
   marked **via API**.

5. **Issue API keys for automation (optional).** Go to **API Keys** in the top
   nav to let scanners / CI pipelines file findings programmatically:
   - Click **Generate key**, give it a name (e.g. `ci-prod-scanner`). The full
     key (`ih_live_…`) is shown **once** — copy it now; only a hash is stored.
   - Use it against the [external API](#external-api-key-auth) below.
   - **Revoke** a key any time; that immediately stops it working without
     affecting your Jira connection.

> **Multi-user:** each account is isolated. Different users have independent
> Jira connections, findings, and API keys — nothing is shared or visible across
> accounts. Try it by opening a second browser/profile and registering another
> user.

### Run components individually (without Docker)

Useful for backend development with hot-reload.

```bash
# Backend (needs a running Postgres, or point DATABASE_URL at SQLite)
cd backend
python -m venv .venv && source .venv/bin/activate   # Python 3.12 or 3.13
pip install -r requirements.txt
export DATABASE_URL="postgresql+asyncpg://identityhub:identityhub@localhost:5432/identityhub"
export APP_ENCRYPTION_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev    # serves http://localhost:5173, talks to the backend on :8000
```

Run the test suite (uses SQLite, no Postgres needed):

```bash
cd backend && .venv/bin/python -m pytest
```

### Quick end-to-end with curl

```bash
# 1. Register (stores the session cookie in cookies.txt)
curl -c cookies.txt -X POST localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"supersecret"}'

# 2. Connect Jira
curl -b cookies.txt -X POST localhost:8000/jira/connect \
  -H 'Content-Type: application/json' \
  -d '{"site_url":"your-site.atlassian.net","jira_email":"me@example.com","api_token":"<token>"}'

# 3. Generate an API key for machine access (note the one-time api_key in the response)
curl -b cookies.txt -X POST localhost:8000/api-keys \
  -H 'Content-Type: application/json' -d '{"name":"ci-scanner"}'

# 4. Create a finding ticket as an external system
curl -X POST localhost:8000/api/v1/findings \
  -H "Authorization: Bearer ih_live_..." \
  -H 'Content-Type: application/json' \
  -d '{"project_key":"NHI","title":"Stale Service Account: svc-deploy-prod","description":"No activity in 90 days."}'
```

---

## Architecture

```
┌───────────────┐        ┌──────────────────────────────────────────┐
│  React (Vite) │  cookie │              FastAPI backend             │
│  UI  :5173    │◄───────►│                                          │
└───────────────┘ session │  /auth     session auth (login/logout)   │
                          │  /jira     connect workspace             │       ┌────────────┐
┌───────────────┐ Bearer  │  /findings create / list tickets   ─────┼──────►│ Jira Cloud │
│ Scanner / CI  │  apikey  │  /api-keys manage external keys          │ httpx │ REST API   │
│ (machines)    │◄───────►│  /api/v1   external machine API          │ Basic └────────────┘
└───────────────┘         └──────────────────┬───────────────────────┘
                                             │ async SQLAlchemy
                                       ┌──────▼──────┐
                                       │  Postgres   │
                                       └─────────────┘
```

**Layering.** The codebase keeps a strict separation of concerns:

- **Routers** (`app/routers/`) — HTTP concerns only: parse/validate request,
  call a service, shape the response. No business logic, no SQL beyond trivial
  lookups.
- **Services** (`app/services/`) — business logic shared across entry points.
  `findings_service.create_finding()` is called by *both* the UI router and the
  external API router, so the two paths cannot drift.
- **Security primitives** (`app/security/`) — password hashing, token
  generation, and encryption isolated into small, individually testable
  modules.
- **Jira client** (`app/services/jira_client.py`) — the only code that knows
  the Jira wire format; everything upstream deals in domain objects.
- **Schemas** (`app/schemas.py`) — Pydantic models define the API contract,
  decoupled from the ORM models in `app/models.py`.

### Runtime topology (containers)

Planned `docker compose` services:

| Service | Image / role | Always running? |
|---|---|---|
| `db` | Postgres 16 | Yes |
| `backend` | FastAPI + uvicorn | Yes |
| `frontend` | React (Vite dev server in dev; static bundle in prod) | Yes |
| `digest` | NHI Blog Digest batch job (bonus) | **No** — one-shot via `docker compose run --rm digest` |

Steady state is **3 long-running containers**; the digest is a batch job that
runs and exits, so no idle container is kept for it (satisfies "any
trigger/scheduled can work").

**Decision — separate `frontend` container vs backend-served bundle:** we keep a
separate `frontend` container in dev for Vite hot-reload and a visibly clean
UI/backend split. A production build would instead serve the static React bundle
from the backend (2 containers, single origin, no CORS). The CORS config in
`app/main.py` exists to support the dev split. *(Final count pending — see the
decision log.)*

## The three-layer identity model

The most important design idea. There are **three distinct credentials**, never
conflated, all linked by one `user_id`:

```
Layer 1 — App login (humans)
  email + password → server-side session → httpOnly cookie

Layer 2 — Jira connection (per user, set once after login)
  Jira email + API token + site URL → AES-GCM encrypted in DB
  IdentityHub calls Jira *on the user's behalf*

Layer 3 — IdentityHub API keys (machines)
  user generates `ih_live_…` in the UI → only a hash is stored
  external scanner/CI authenticates to /api/v1 with it
```

A request flow for the external API:

```
Scanner ──Bearer ih_live_…──► /api/v1/findings
                                │ hash(key) → api_keys row → user_id
                                │ decrypt that user's Jira token
                                └─► Jira POST /rest/api/3/issue (Basic email:token)
```

**Why separate Layer 2 and Layer 3?**
- Revoking an IdentityHub API key never touches the user's Jira connection (and
  vice versa).
- The external system never sees Jira credentials — least privilege.
- Per-key lifecycle: name, revoke, `last_used_at`, independent of Jira.
- Clean multi-tenancy: auth resolves to a `user_id`, and every query filters on
  it — the tenant boundary lives in one place (`app/deps.py`).

## Data model

`app/models.py`. For this POC **1 user == 1 tenant**; the schema is shaped so a
separate `tenant_id` (an org with many users) could be added later without
restructuring.

| Table | Purpose | Sensitive fields & handling |
|---|---|---|
| `users` | App accounts | `password_hash` (argon2id) — never the password |
| `jira_connections` | A user's Jira credential | `api_token_ciphertext` + `api_token_nonce` (AES-256-GCM) — never plaintext |
| `api_keys` | IdentityHub keys for `/api/v1` | `key_hash` (SHA-256) + `key_prefix` for display — plaintext shown once |
| `sessions` | Server-side sessions | opaque id is the cookie value; deleting the row revokes instantly |
| `finding_tickets` | Local record of tickets created via the app | scoped by `user_id`; source of truth for the "recent" view |

---

## Design decisions

Each choice below is something a reviewer might ask "why?" about.

### Stack: Python + FastAPI + React + Postgres
- **FastAPI** gives async I/O (every request fans out to Jira over the network,
  so non-blocking matters), Pydantic validation for free, and auto-generated
  OpenAPI docs at `/docs` — useful for the "external systems" audience.
- **Postgres over SQLite**: a security/multi-tenancy story is more credible on a
  real RDBMS, and it matches a production deployment. Run via Docker so the
  reviewer needs zero local DB setup.
- **SQLite is used only for the test suite** (`aiosqlite`) — fast, no container
  required. The code stays portable across both because we use the async
  SQLAlchemy ORM rather than raw SQL. The one engine difference we handle
  explicitly: SQLite returns timezone-naive datetimes while Postgres returns
  aware ones, so session-expiry comparison in `app/deps.py` normalizes naive
  values to UTC (harmless on Postgres, required on SQLite).
- **React + Vite + TypeScript**: fast scaffold, clear client/server boundary
  that satisfies the "separation between UI and backend layers" criterion.

### Frontend structure
- **`src/api/client.ts`** — the single typed boundary to the backend. All
  requests send `credentials: "include"` (the session cookie) and normalize
  failures into an `ApiError` carrying the backend's `detail` message, so the
  clear errors the backend produces surface verbatim in the UI.
- **`src/auth/AuthContext.tsx`** — holds the session user; calls `/auth/me` on
  mount so a page refresh restores the session.
- **`src/pages/`** — `LoginPage` (login/register toggle), `DashboardPage`
  (orchestrates the Jira panel + create form + recent tickets), `ApiKeysPage`.
- **`src/components/`** — presentational pieces: `JiraConnectionPanel`,
  `CreateFindingForm` (project field is a datalist so the user can pick *or*
  type a project key — Requirement: "selects / writes a Jira project"),
  `RecentTickets` (links each issue to Jira in a new tab), `Layout`, `Alert`.

### Auth: email + password with server-side sessions (not JWT, not OAuth)
- **Password over magic-link / social login** for the app itself: zero external
  dependencies (no SMTP, no Google client config) so the reviewer can run it
  immediately, *and* it lets us demonstrate secure password handling (argon2id,
  timing-equalized login) — which is part of what's being graded.
- **Server-side sessions over JWT**: logout and expiry must revoke access
  *immediately*. A stateless JWT can't be revoked without extra
  denylist machinery; deleting a `sessions` row is simpler and strictly safer
  for a credential-handling product. The cookie is `httpOnly`, `SameSite=Lax`,
  and `Secure` in production.

### Jira auth: API token (Basic) over OAuth 2.0 3LO
- An API token + email is **runnable by the reviewer in two minutes** — create
  a token at id.atlassian.com, paste it, done. OAuth 3LO would require
  registering an Atlassian developer app, redirect URLs, and a client secret,
  adding significant friction for a POC.
- **Trade-off documented:** OAuth 3LO is the better production answer for
  multi-tenant SaaS (no long-lived shared secret, granular scopes, user-
  revocable). The token model here is encapsulated behind `JiraClient` and the
  `jira_connections` table, so swapping in OAuth later means changing how the
  credential is obtained/refreshed, not the rest of the app.

### Recent-tickets view: a local table, *plus* a Jira label
- Requirement #3 asks for tickets *"created from this app"* — Jira has no native
  way to express that filter. We persist a `finding_tickets` row for every
  ticket we create (the source of truth for the list: fast, always available,
  unambiguously scoped per tenant) **and** stamp each Jira issue with an
  `identityhub` label so it's identifiable inside Jira too.
- **Trade-off:** the local record can drift if a ticket is deleted directly in
  Jira. Acceptable for a POC; a production version would reconcile via the label
  + JQL.

### Shared service layer for UI and API
- `findings_service.create_finding()` is the single code path for ticket
  creation. The UI router and the external API router both call it (differing
  only in `source="ui"` vs `"api"` and their auth dependency), guaranteeing
  identical validation, tenancy, and Jira behavior.

### Why not the `jira` Python package?

We use a small hand-written async client (`app/services/jira_client.py`, ~120
lines) over the Jira REST API instead of a packaged SDK such as `jira` or
`atlassian-python-api`. Reasons:

1. **Async fit.** The backend is fully async (FastAPI + async SQLAlchemy +
   `httpx.AsyncClient`). The popular `jira` package is synchronous
   (`requests`-based); dropping it in would mean blocking calls inside async
   handlers or wrapping every call in `run_in_executor` — messier than the thin
   client we have.
2. **Tiny surface area.** We need exactly three operations: verify credentials
   (`/myself`), list projects, and create an issue. A general-purpose SDK pulls
   in a large dependency wrapping dozens of endpoints we never call — more to
   audit and more supply-chain surface, which cuts against the security
   criterion being graded.
3. **Error-message control.** Clear, meaningful errors are an explicit grading
   area. The client deliberately catches Jira responses and translates them into
   user-facing messages ("Jira rejected the credentials… the token may have been
   revoked") and maps upstream status codes to the right client-facing ones
   (Jira `401` → our `502` with a reconnect hint; Jira `400` → our `400`). An SDK
   would require unwrapping its own exception types and re-mapping anyway.
4. **Explicitness for review.** The exercise asks us to "understand the choices
   made." A visible client showing the exact endpoints, auth scheme (HTTP Basic
   with `email:api_token`), and payload format (Atlassian Document Format for v3
   descriptions) is easier to reason about and defend than "the library handles
   it."

**Where an SDK would win** (and what we'd reach for in production): many
endpoints, pagination, retries/backoff, rate-limit handling, or OAuth 3LO token
refresh. At that scale `atlassian-python-api` (which does offer async support)
saves real work. For three endpoints in a POC, the thin client is the cleaner
call.

---

## Security practices

- **Passwords**: argon2id (memory-hard, current OWASP recommendation). Login
  runs a dummy verify when the email is unknown so response timing doesn't leak
  which emails are registered.
- **Jira tokens**: AES-256-GCM (authenticated encryption) with a fresh random
  96-bit nonce per record. The master key comes from `APP_ENCRYPTION_KEY` in the
  environment — never stored in the DB or source.
- **API keys**: high-entropy random `ih_live_…` values; only a SHA-256 hash and
  a short display prefix are stored. Plaintext is returned exactly once.
- **Sessions**: opaque server-side ids in `httpOnly` + `SameSite=Lax` cookies,
  `Secure` in production; revocable by row deletion.
- **Multi-tenancy**: every tenant-scoped query filters on `user_id`. Cross-tenant
  object access (e.g. revoking someone else's API key) returns `404`, not `403`,
  so existence isn't leaked.
- **Validation**: Pydantic schemas validate all input; a custom handler returns a
  single readable `detail` message for both humans and machines.
- **Secrets** live in environment variables (`.env`), never committed.

---

## API reference

### UI (session cookie auth)
| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account, start session |
| POST | `/auth/login` | Log in |
| POST | `/auth/logout` | Log out (revoke session) |
| GET | `/auth/me` | Current user + Jira-connected flag |
| POST | `/jira/connect` | Verify & store Jira credentials |
| GET | `/jira/connection` | Current connection metadata |
| DELETE | `/jira/connection` | Disconnect Jira |
| GET | `/jira/projects` | List projects in the workspace |
| POST | `/findings` | Create a finding ticket |
| GET | `/findings?project_key=…` | 10 most recent app-created tickets |
| POST | `/api-keys` | Create an API key (plaintext shown once) |
| GET | `/api-keys` | List keys (prefix + metadata only) |
| DELETE | `/api-keys/{id}` | Revoke a key |

### External (API-key auth)
| Method | Path | Description | Codes |
|---|---|---|---|
| POST | `/api/v1/findings` | Programmatically create a finding ticket | `201`, `400`, `401`, `409`, `422`, `502` |

`409` means no Jira workspace is connected for the key's owner; `502` means Jira
itself rejected the request (e.g. stored credentials were revoked).

---

## Assumptions & scope

- **1 user = 1 tenant**, with one Jira connection per user. Documented above;
  the schema anticipates a future `tenant_id`.
- **Issue type is `Task`** with labels `identityhub`, `nhi-finding`. A real
  integration would let the user pick the project's available issue types and
  map NHI severity to priority/custom fields.
- **Projects list shows the first 50** (no pagination) — sufficient for a POC.
- **Jira Cloud only** (REST API v3, always HTTPS). Jira Server/Data Center uses a
  different auth model and isn't targeted.
- The **recent-tickets list** reflects tickets created *through this app*, not
  all tickets in the project (by design — matches the requirement).

---

## Decision log

A running record of significant decisions, newest first. This README is kept as
the living source of truth — every change to the project updates it here.

| Date | Decision | Rationale | Status |
|---|---|---|---|
| 2026-06-09 | Frontend: React + Vite + TS, single typed API client, datalist project picker | Strict-typed wiring, errors surfaced from backend `detail`, picker supports select-or-type | ✅ implemented (builds clean) |
| 2026-06-09 | Backend stack: FastAPI + async SQLAlchemy + Postgres | Async fits the Jira-fan-out workload; real RDBMS for a credible multi-tenancy story | ✅ implemented & smoke-tested |
| 2026-06-09 | Three-layer identity model (session / encrypted Jira token / hashed API key) | Separation of credentials, least privilege, independent revocation | ✅ implemented |
| 2026-06-09 | Hand-written async Jira client over the `jira` SDK | Async fit, tiny surface area, error-message control, reviewability | ✅ implemented |
| 2026-06-09 | SQLite for tests, Postgres for the app | Fast container-free tests; portable via the ORM. TZ-normalization guard added in `deps.py` | ✅ implemented |
| 2026-06-09 | Docker Compose stack (Postgres + backend + frontend) as the primary run path | "Frictionless to run" — `docker compose up --build`, verified end-to-end against live Postgres | ✅ implemented |
| 2026-06-09 | Test suite on SQLite with a mocked Jira client (28 tests) | No network/Postgres needed; covers auth, findings, external API, and cross-tenant isolation | ✅ implemented (28 passing) |
| 2026-06-09 | 3 long-running containers; `frontend` stays a separate Vite container | Hot-reload + visibly clean UI/backend split. Documented that prod could serve the bundle from the backend for a 2-container, single-origin setup | ✅ resolved |
| 2026-06-09 | Digest (bonus) runs as a one-shot container behind a Compose profile | It's a batch job; no reason to idle a container. Started via `docker compose run --rm digest` | ⏳ planned |

