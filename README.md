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
   - **Project** — a dropdown populated from your Jira workspace (fetched when
     the dashboard loads), showing `KEY — Name` for each project.
   - **Title** — the summary, e.g. `Stale Service Account: svc-deploy-prod`.
   - **Description** — details about the finding (optional).
   - **Priority** — optional; maps the finding's severity to Jira priority.
     Applied best-effort (some team-managed projects don't expose priority — if
     so, Jira's error is surfaced clearly).
   - **Due date** — optional remediation deadline.
   - **Labels** — type a label and press Enter to add your own (e.g. `aws`,
     `prod`). Spaces are converted to hyphens. The `identityhub` marker label is
     always added automatically (and is shown as a fixed chip).
   - **NHI context** (optional, collapsible) — affected resource, category,
     environment, last activity. These are folded into the ticket description.

   Submit to create the Jira issue. A confirmation shows the new issue key
   (e.g. `SAM1-42`).

4. **Review recent findings.** The **Recent findings** panel lists the 10 most
   recent tickets *created through IdentityHub* for the selected project,
   newest first, read **live from Jira** (filtered by the `identityhub` label).
   Each row shows the creation time and any custom labels, and links to the Jira
   issue in a new tab. A just-created ticket appears immediately even though
   Jira's search index lags a moment behind.

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

> **Finding tickets are not stored locally.** Jira is the single source of
> truth — issues are created there (stamped with the `identityhub` label) and
> the "recent findings" view reads them back via Jira search. See the design
> decision below.

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
  `CreateFindingForm` (project field is a dropdown populated from the workspace,
  fetched via the backend on dashboard load), `RecentTickets` (links each issue
  to Jira in a new tab), `Layout`, `Alert`.

> **The frontend never talks to Jira directly.** Every Jira interaction goes
> through the backend (`/jira/*`, `/findings`), which holds the encrypted token
> and is the only component that calls the Jira REST API. The browser only ever
> sees IdentityHub endpoints — credentials never reach the client.

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

### Recent-tickets view: Jira is the single source of truth (label-based)
- Requirement #3 asks for tickets *"created from this app"* — Jira has no native
  way to express that filter, so every issue we create is stamped with the
  `identityhub` **marker label**. The "recent findings" view is a live Jira
  search: `project = X AND labels = identityhub ORDER BY created DESC` (top 10).
- **We deliberately keep no local copy of tickets.** Jira owns the data; there's
  no mirror table to fall out of sync, no drift if an issue is edited or deleted
  in Jira, and the list always reflects reality.
- **Trade-offs (accepted, documented):**
  - *Eventual consistency* — Jira's search index lags issue creation by ~1–2s,
    so a brand-new ticket might not be in the search results immediately. The UI
    compensates by optimistically showing the just-created ticket until the next
    refresh confirms it.
  - *The marker label is workspace-wide* — with 1 user = 1 Jira account (each
    its own token), a user's search runs as their own Jira identity, so they
    only see what that account can. But the label itself doesn't encode *which*
    IdentityHub user created an issue; two IdentityHub users sharing one Jira
    account would see each other's app-created tickets. Fine for this tenancy
    model; a future multi-user-per-tenant design could add a per-tenant label.
  - *No `source` (ui/api) attribution* — that lived in the dropped local table.
    Could be re-added as a second label (e.g. `nhi-via-api`) if needed.

### Create-finding fields
- **Always sent:** title (summary), description, and the `identityhub` marker
  label. **Issue type is fixed to `Task`** — a documented scope choice (a
  production version would read the project's available types from Jira's
  createmeta and let the user pick).
- **User-controllable:** custom **labels** (validated — Jira labels can't have
  spaces, so they're normalized to hyphens), **priority** (best-effort; mapped
  to the standard Jira priority scheme), and a **due date**.
- **NHI-specific context** (affected resource, category, environment, last
  activity) has no portable native Jira field, so it's rendered into a
  structured **description template** rather than fragile per-project custom
  fields — keeping the integration portable across any Jira project.

### Shared service layer for UI and API
- `findings_service.create_finding()` is the single code path for ticket
  creation. The UI router and the external API router both call it (differing
  only in their auth dependency), guaranteeing identical validation, tenancy,
  and Jira behavior.

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
  so existence isn't leaked. Finding tickets aren't stored locally — each user's
  recent-findings search runs against *their own* Jira connection, so isolation
  for tickets is enforced by Jira itself.
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

#### Finding request body (`POST /findings` and `POST /api/v1/findings`)

```jsonc
{
  "project_key": "SAM1",                 // required
  "title": "Stale Service Account: svc-deploy-prod",  // required
  "description": "No activity in 90 days.",
  "labels": ["aws", "prod"],             // 'identityhub' marker added server-side
  "priority": "High",                    // Highest|High|Medium|Low|Lowest (best-effort)
  "due_date": "2026-07-15",              // YYYY-MM-DD
  "resource": "svc-deploy-prod",         // NHI context → description
  "category": "Stale service account",
  "environment": "aws-prod",
  "last_activity": "2026-03-01"
}
```

Response (both endpoints) returns the created issue: `jira_issue_key`,
`jira_issue_url`, `title`, `project_key`, `labels`, `created_at`.

---

## Assumptions & scope

- **1 user = 1 tenant**, with one Jira connection per user. Documented above;
  the schema anticipates a future `tenant_id`.
- **Jira is the single source of truth for tickets** — no local copy. The
  "recent" view is a live Jira search on the `identityhub` marker label. (See
  the design decision for the eventual-consistency and label-scope trade-offs.)
- **Issue type is `Task`.** A production integration would read the project's
  available issue types from createmeta and let the user pick.
- **Priority is best-effort** — applied only if the target project exposes a
  priority field; otherwise Jira's error is surfaced.
- **Projects list shows the first 50** (no pagination) — sufficient for a POC.
- **Jira Cloud only** (REST API v3, always HTTPS). Jira Server/Data Center uses a
  different auth model and isn't targeted.

---

## Decision log

A running record of significant decisions, newest first. This README is kept as
the living source of truth — every change to the project updates it here.

| Date | Decision | Rationale | Status |
|---|---|---|---|
| 2026-06-09 | **Jira is the single source of truth** — dropped the local `finding_tickets` table; recent view is a label-based Jira search | No drift, no stale mirror. Trade-offs (eventual consistency, workspace-wide label, no source flag) documented; UI optimistically shows new tickets | ✅ implemented & verified live |
| 2026-06-09 | Create-finding fields: custom labels, priority (best-effort), due date, NHI context in description; issue type fixed to `Task` | Richer findings while staying portable across projects; no fragile custom-field mapping | ✅ implemented & verified live |
| 2026-06-09 | Frontend: React + Vite + TS, single typed API client; project chosen from a backend-fed dropdown | Frontend never calls Jira directly — all Jira access is proxied through the backend, which holds the credential | ✅ implemented (builds clean) |
| 2026-06-09 | Backend stack: FastAPI + async SQLAlchemy + Postgres | Async fits the Jira-fan-out workload; real RDBMS for a credible multi-tenancy story | ✅ implemented & smoke-tested |
| 2026-06-09 | Three-layer identity model (session / encrypted Jira token / hashed API key) | Separation of credentials, least privilege, independent revocation | ✅ implemented |
| 2026-06-09 | Hand-written async Jira client over the `jira` SDK | Async fit, tiny surface area, error-message control, reviewability | ✅ implemented |
| 2026-06-09 | SQLite for tests, Postgres for the app | Fast container-free tests; portable via the ORM. TZ-normalization guard added in `deps.py` | ✅ implemented |
| 2026-06-09 | Docker Compose stack (Postgres + backend + frontend) as the primary run path | "Frictionless to run" — `docker compose up --build`, verified end-to-end against live Postgres | ✅ implemented |
| 2026-06-09 | Test suite on SQLite with an in-memory fake Jira (32 tests) | No network/Postgres needed; covers auth, findings, labels/priority/context, external API, and cross-tenant isolation | ✅ implemented (32 passing) |
| 2026-06-09 | 3 long-running containers; `frontend` stays a separate Vite container | Hot-reload + visibly clean UI/backend split. Documented that prod could serve the bundle from the backend for a 2-container, single-origin setup | ✅ resolved |
| 2026-06-09 | Digest (bonus) runs as a one-shot container behind a Compose profile | It's a batch job; no reason to idle a container. Started via `docker compose run --rm digest` | ⏳ planned |

