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
- [Multi-tenancy](#multi-tenancy)
- [Data model](#data-model)
- [Design decisions](#design-decisions)
  - [Why not the `jira` Python package?](#why-not-the-jira-python-package)
- [Security practices](#security-practices)
- [API reference](#api-reference)
- [NHI Blog Digest (bonus)](#nhi-blog-digest-bonus)
- [Assumptions & scope](#assumptions--scope)

---

## What it does

| Requirement | Status | Where |
|---|---|---|
| App login / logout, secure server-side sessions | ✅ | `app/routers/auth.py` |
| Multi-tenant isolation (no cross-user data leakage) | ✅ | `app/deps.py`, every query scoped by `user_id` |
| Connect a Jira workspace (token encrypted at rest via Vault Transit) | ✅ | `app/routers/jira.py` |
| Create an NHI finding ticket (project + title + description) | ✅ | `app/routers/findings.py` |
| Recent tickets view (10 most recent created via this app, per project) | ✅ | `app/routers/findings.py` |
| External REST API with API-key auth, validation, status codes | ✅ | `app/routers/external_api.py` |
| Web UI (login, Jira connect, create finding, recent tickets, API keys) | ✅ | `frontend/` (React + Vite + TS) |
| Bonus: NHI Blog Digest automation | ✅ | `app/digest/` (periodic worker) |

## Setup

### Prerequisites
- **Docker + Docker Compose** (the recommended path — nothing else to install).
- A free **Jira Cloud** account (atlassian.com) and a **Personal API Token**
  from <https://id.atlassian.com/manage-profile/security/api-tokens>.

### Run everything with Docker Compose (recommended)

```bash
# Build and start the stack (Postgres + Vault + backend + frontend).
docker compose up --build
```

That's it — no config needed for a local run. Five services start (Postgres,
Redis, Vault, backend, frontend):

| URL | What |
|---|---|
| <http://localhost:5173> | **Web app** — open this to use IdentityHub |
| <http://localhost:8000/docs> | Interactive API docs (OpenAPI/Swagger) |
| <http://localhost:8000/health> | Health check |
| <http://localhost:8200> | Vault dev UI/API (token `root`) — Transit engine |

Jira API tokens are encrypted with **Vault's Transit engine** out of the box;
the backend provisions the `identityhub` transit key on startup.

Stop with `Ctrl-C`, or `docker compose down` (add `-v` to also wipe the
Postgres volume and start fresh).

### Configuration

All configuration is via environment variables (read from `.env` by Compose);
defaults work for a local run.

| Variable | Default | Purpose |
|---|---|---|
| `CRYPTO_BACKEND` | `vault` | Token-encryption backend: `vault` (Transit) or `local` (AES-256-GCM). |
| `VAULT_ADDR` / `VAULT_TOKEN` | Compose Vault / `root` | Vault address + token (used when `CRYPTO_BACKEND=vault`). |
| `APP_ENCRYPTION_KEY` | weak dev placeholder | AES-256-GCM master key — **only used when `CRYPTO_BACKEND=local`**. Set a stable 32-byte secret for real use; rotating it makes stored tokens undecryptable. |
| `DATABASE_URL` | Compose Postgres | Async SQLAlchemy connection string |
| `REDIS_URL` | Compose Redis | Session store connection string |
| `SESSION_TTL_SECONDS` | `604800` (7d) | Session lifetime |
| `SECURE_COOKIES` | `false` | Set `true` behind HTTPS in production |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | CORS origin allowed to send the session cookie |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | — | Set all three to enable SSO login (e.g. Auth0). Unset = email+password. |
| `OIDC_REDIRECT_URI` | `…/auth/oidc/callback` | Must match an Allowed Callback URL at the IdP |
| `NHI_FIELD_MAP` | — | Optional JSON mapping NHI context fields to Jira custom fields; unmapped fields fall back to the description |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | Ollama / `llama3.2:1b` / — | Free LLM for the digest (OpenAI-compatible). Point at Groq/Gemini/etc. by overriding |
| `DIGEST_INTERVAL_SECONDS` | `86400` | How often the digest runs |
| _(digest targets)_ | — | Per-user: each user picks project(s) in the app (Report → NHI Blog Digest); no env needed |

### Enabling SSO with a hosted IdP (Auth0)

Login is email+password by default. To use SSO instead, register an app at your
IdP and set the `OIDC_*` variables. The integration is **provider-agnostic**
(OIDC discovery), so Okta/Google/Entra work the same way with their issuer —
the steps below use **Auth0**.

**1. Create a tenant + application**
1. Sign up / log in at [auth0.com](https://auth0.com). The first login creates a
   **tenant** with a domain like `your-tenant.us.auth0.com` (region suffix varies).
2. **Applications → Applications → Create Application**.
3. Name it (e.g. `IdentityHub`), choose **Regular Web Applications**, **Create**.
   Then open the **Settings** tab.

**2. Copy the three values** from Settings:
- **Domain** (e.g. `your-tenant.us.auth0.com`)
- **Client ID**
- **Client Secret**

**3. Configure the URLs** (under *Application URIs* — must match exactly, then
**Save Changes**):

| Field | Value |
|---|---|
| Allowed Callback URLs | `http://localhost:8000/auth/oidc/callback` |
| Allowed Logout URLs | `http://localhost:5173` |
| Allowed Web Origins | `http://localhost:5173` |

A callback-URL mismatch is the most common cause of OIDC login failures.

**4. Ensure you have a user to log in as.** New tenants usually have the
**Username-Password-Authentication** database connection enabled. Create a test
user under **User Management → Users → Create User** if needed.

**5. Set the env** in `.env` at the repo root (gitignored — the secret is not
committed). `OIDC_ISSUER` is the **Domain with `https://`**, no path:
```bash
OIDC_ISSUER=https://your-tenant.us.auth0.com
OIDC_CLIENT_ID=<Client ID>
OIDC_CLIENT_SECRET=<Client Secret>
```

**6. Start it:** `docker compose up -d --build backend`. The login screen now
shows **Log in with SSO**, and the password endpoints return `403`. The backend
derives the discovery URL `…/.well-known/openid-configuration` from the issuer.

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

The UI has three tabs: **Report** (connect Jira + create findings), **Findings**
(browse everything), and **API Keys**.

3. **Report an NHI finding.** On the **Report** tab, in **New NHI finding**:
   - **Project** — a dropdown populated from your Jira workspace (fetched when
     the dashboard loads), showing `KEY — Name` for each project.
   - **Title** — the summary, e.g. `Stale Service Account: svc-deploy-prod`.
   - **Description** — details about the finding (optional).
   - **Priority** — optional; maps the finding's severity to Jira priority.
     Applied best-effort (some team-managed projects don't expose priority — if
     so, Jira's error is surfaced clearly).
   - **Labels** — type a label and press Enter to add your own (e.g. `aws`,
     `prod`). Spaces are converted to hyphens. The `identityhub` marker label is
     always added automatically (and is shown as a fixed chip).
   - **NHI context** (optional, collapsible) — affected resource, category,
     environment, and last activity (a date picker). These are folded into the
     ticket description.

   Submit to create the Jira issue. A confirmation shows the new issue key
   (e.g. `SAM1-42`). The Jira issue also gets a **"View in IdentityHub"** web
   link (a Jira *remote link*) that opens the app focused on that project — a
   cross-reference back from Jira to the NHI platform.

4. **Review recent findings (Report tab).** The **Recent findings** panel lists
   the 10 most recent tickets *created through IdentityHub* for the selected
   project, newest first, read **live from Jira** (filtered by the `identityhub`
   label). A just-created ticket appears immediately even though Jira's search
   index lags a moment behind.

5. **Browse all findings (Findings tab).** Lists app-created findings across
   your workspace, with a **project filter** (or **All projects**). Clicking a
   finding opens an **in-app detail page** — *not* the Jira issue directly —
   reconstructed from Jira (the source of truth): title, description, labels,
   priority/status/assignee, and the NHI context. From there an **"Open in
   Jira ↗"** button jumps to the actual issue. (The same in-app detail page is
   used from the Report tab's recent list.)

6. **Issue API keys for automation (optional).** Go to **API Keys** in the top
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
# Without a Vault instance, use the local AES-GCM backend:
export CRYPTO_BACKEND=local
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
└───────────────┘         └────────┬─────────────────┬───────────────┘
                                   │ async SQLAlchemy │ Transit encrypt/decrypt
                            ┌──────▼──────┐    ┌──────▼───────┐
                            │  Postgres   │    │ Vault (Transit)│
                            │ users/keys/ │    │  token key never│
                            │ connections │    │  leaves Vault   │
                            └─────────────┘    └────────────────┘
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
| `redis` | Redis 7 — server-side session store | Yes |
| `vault` | HashiCorp Vault (dev) — Transit engine encrypts Jira tokens | Yes |
| `backend` | FastAPI + uvicorn | Yes |
| `frontend` | React (Vite dev server in dev; static bundle in prod) | Yes |
| `digest` | NHI Blog Digest periodic worker (bonus) | Only under the `digest` profile |
| `ollama` | Free local LLM for the digest (bonus) | Only under the `digest` profile |

Steady state is **5 long-running containers**. The bonus `digest` + `ollama`
sit behind a Compose **profile**, so the default `up` stays lean and doesn't
pull the large Ollama image; start them with `docker compose --profile digest
up`. Set `CRYPTO_BACKEND=local` to drop Vault.

**Decision — separate `frontend` container vs backend-served bundle:** we keep a
separate `frontend` container in dev for Vite hot-reload and a visibly clean
UI/backend split. A production build would instead serve the static React bundle
from the backend (2 containers, single origin, no CORS). The CORS config in
`app/main.py` exists to support the dev split.

## The three-layer identity model

The most important design idea. There are **three distinct credentials**, never
conflated, all linked by one `user_id`:

```
Layer 1 — App login (humans)
  password (default) OR OIDC via a hosted IdP (e.g. Auth0)
  → server-side session → httpOnly cookie

Layer 2 — Jira connection (per user, set once after login)
  Jira email + API token + site URL → Vault-Transit (or AES-GCM) encrypted in DB
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

## Multi-tenancy

The model is **1 user = 1 tenant**, and the tenant boundary is a single,
consistently-applied key: `user_id`.

- **One place resolves identity.** Both auth schemes in `app/deps.py` collapse to
  a `User`: the **session cookie** (`current_user`) for the UI, and the
  **API key** (`api_key_user`) for the external API, which resolves to the key's
  *owning* user. Downstream code never trusts client-supplied ids — it scopes by
  the `user.id` it derived from the credential.
- **Every tenant-scoped query filters on `user_id`.** Jira connection (unique per
  user), API keys, and sessions are all bound to it. Cross-tenant object access
  (e.g. revoking someone else's key) returns **`404`, not `403`**, so existence
  isn't leaked.
- **Findings isolation is delegated to Jira.** There's no local ticket store, so
  there's nothing shared to leak: each user's create/search runs against *their
  own* encrypted Jira connection, and an external API call acts on the key
  owner's connection — never another tenant's.
- **Credential isolation.** Each tenant's Jira token is encrypted at rest (Vault
  Transit) and only decrypted transiently for that user's request; API keys are
  stored only as hashes.
- **Concurrent users don't interfere.** The stack is async with no shared
  per-user mutable state — each request resolves its own user and DB session.
- **Verified** in `backend/tests/test_multitenancy.py`: findings isolated across
  users, no cross-tenant API-key revocation, and an API key routes creation to
  its owner's Jira.

**Limitations (by design, documented):** there's no organization-with-many-users
concept — the schema is shaped so a separate `tenant_id` could be added later
without restructuring. And the `identityhub` marker label is workspace-wide, so
two IdentityHub users sharing *one* Jira account would see each other's
app-created findings; with distinct Jira accounts (the normal case) isolation
holds.

## Data model

`app/models.py`. For this POC **1 user == 1 tenant**; the schema is shaped so a
separate `tenant_id` (an org with many users) could be added later without
restructuring.

| Table | Purpose | Sensitive fields & handling |
|---|---|---|
| `users` | App accounts | `password_hash` (argon2id) — never the password |
| `jira_connections` | A user's Jira credential | `api_token_ciphertext` (Vault Transit `vault:v1:…` by default, or AES-256-GCM + `api_token_nonce` locally) — never plaintext |
| `api_keys` | IdentityHub keys for `/api/v1` | `key_hash` (SHA-256) + `key_prefix` for display — plaintext shown once |
| `digest_subscriptions` | Per-user blog-digest opt-in | `(user_id, project_key)` — which projects the digest files into, per user |

> **Sessions are not in Postgres** — they live in **Redis** (opaque id → user_id,
> with a TTL). See the app-login design decision.
>
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
- **`src/pages/`** — `LoginPage` (login/register or SSO), `DashboardPage` (the
  **Report** tab: Jira panel + create form + recent), `FindingsListPage` (the
  **Findings** tab: project filter + list), `FindingDetailPage` (in-app finding
  detail + "Open in Jira"), `ApiKeysPage`.
- **`src/components/`** — presentational pieces: `JiraConnectionPanel`,
  `CreateFindingForm` (project field is a dropdown populated from the workspace,
  fetched via the backend on dashboard load), `RecentTickets` (rows link to the
  in-app detail page), `Layout`, `Alert`.

> **The frontend never talks to Jira directly.** Every Jira interaction goes
> through the backend (`/jira/*`, `/findings`), which holds the encrypted token
> and is the only component that calls the Jira REST API. The browser only ever
> sees IdentityHub endpoints — credentials never reach the client.

### App login: server-side sessions, with OIDC (hosted IdP) or password
- **Server-side sessions over JWT** (always): logout and expiry must revoke
  access *immediately*. A stateless JWT can't be revoked without extra denylist
  machinery; deleting a session is simpler and strictly safer for a
  credential-handling product. The cookie is `httpOnly`, `SameSite=Lax`, and
  `Secure` in production. **This session layer is identical regardless of how
  the user authenticated** — the login method only changes how we *establish*
  the session.
- **Sessions live in Redis**, not the DB: an opaque session id → `user_id` with
  the session TTL as the key expiry (Redis ages them out automatically — no
  `expires_at` column or cleanup job). An out-of-process store is what makes
  sessions survive restarts and work across multiple workers/replicas (an
  in-process dict would log everyone out on deploy and break behind a load
  balancer). Logout deletes the key → instant revocation. Swappable behind
  `app/session_store.py`.
- **OIDC via a hosted IdP (e.g. Auth0) when configured** — the production path.
  Authorization Code flow + PKCE (Authlib), endpoints discovered from the
  provider's `/.well-known/openid-configuration`. On callback we validate the
  token, upsert a local user by the IdP `sub` claim, and start our normal
  session. SSO/MFA/deprovisioning become the IdP's responsibility, and `org`/
  `groups` claims map cleanly onto the future `tenant_id`.
- **Password fallback when OIDC isn't configured** — keeps `docker compose up`
  and the test suite running with zero external dependencies, and demonstrates
  secure password handling (argon2id, timing-equalized login). The mode is
  chosen by config presence (`OIDC_ISSUER`/`CLIENT_ID`/`CLIENT_SECRET`); when
  OIDC is on, the password endpoints return `403`.
- **Pluggable boundary:** only `routers/auth.py` (login establishment) and the
  `users` table (`idp_issuer`/`idp_subject` vs `password_hash`) differ between
  modes; `deps.py`, sessions, and every other router are untouched.

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

### Credential encryption: Vault Transit (default), pluggable backend
- The reversible secret we must protect is the **Jira API token** (we need the
  plaintext to call Jira). The naive approach — AES in the app with the key in an
  env var — means anyone who can read the process environment can decrypt every
  tenant's token. That's the weakness Vault removes.
- **Default backend is HashiCorp Vault's Transit engine** (encryption-as-a-
  service): the backend asks Vault to encrypt/decrypt, and the key material
  never leaves Vault. We store the `vault:v1:…` ciphertext; decryption is a
  just-in-time round-trip when building a Jira request.
- **Pluggable by design.** Both backends live behind `encrypt()`/`decrypt()` in
  `app/security/crypto.py`, selected by `CRYPTO_BACKEND`. Nothing else in the
  app (routers, services, ORM) knows which is active — the abstraction boundary
  was chosen so the secret backend is swappable. `local` (AES-256-GCM) is the
  fallback for Vault-free runs and tests.
- **Trade-offs / caveats:**
  - Vault **dev mode is in-memory and auto-unsealed** — a restart loses the
    Transit key, making stored tokens undecryptable. Fine to *demonstrate* the
    integration; production runs Vault with persistent storage and a real
    unseal/auth flow (e.g. AppRole instead of a root token).
  - Switching `CRYPTO_BACKEND` after tokens are stored makes existing
    ciphertext undecryptable (different key custodians) — same caveat as a key
    rotation; users would re-connect Jira.
  - A cloud **KMS** (AWS/GCP) is an equally valid production choice and would
    drop into the same interface.

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
  spaces, so they're normalized to hyphens) and **priority** (best-effort;
  mapped to the standard Jira priority scheme). We deliberately *don't* expose
  Jira-native scheduling fields like **due date** — that's a Jira-side workflow
  concern, not an attribute of the NHI finding itself.
- **NHI-specific context** (affected resource, category, environment, and a
  last-activity date) has no portable native Jira field, so by default it's
  rendered into a structured **description template** — keeping the integration
  portable across any Jira project with zero Jira-side setup. It can optionally
  be written to real Jira custom fields (see below).

### NHI context → Jira custom fields (optional mapping)
Jira custom fields aren't portable: they must be **created by an admin first**,
are addressed by opaque ids (`customfield_10042`), must be on the project's
screen, and are configured per-project on team-managed projects. So mapping is
**opt-in**, not the default.

- **Chosen: Option 1 — a deployment-level `NHI_FIELD_MAP` env var** (JSON). It
  maps each NHI field to a Jira custom-field id + type:
  ```json
  {
    "resource":      { "id": "customfield_10042", "type": "text" },
    "category":      { "id": "customfield_10043", "type": "option" },
    "environment":   { "id": "customfield_10044", "type": "text" },
    "last_activity": { "id": "customfield_10045", "type": "date" }
  }
  ```
  On create, mapped fields are sent as real Jira fields (the `type` controls the
  value shape: `text`/`date` → scalar, `option` → `{"value": …}`, `array` →
  `[{"value": …}]`); **anything unmapped falls back to the description**. A
  malformed map fails soft (degrades to the description). Simple, no schema or
  per-tenant plumbing — right for a POC where one Jira/project is in play.
- **Possible enhancement: Option 2 — per-connection, project-scoped mapping in
  the DB.** A JSON column on `jira_connections` keyed by project
  (`{"SAM1": {...}, "KAN": {...}}`), edited via a settings screen, validated
  against `createmeta`. This is the multi-tenant-correct shape (each tenant maps
  their own fields per project) but costs a DB column, a config API/UI, and
  validation — deferred as future work.

### Cross-reference: Jira → IdentityHub
- After creating an issue we attach a Jira **remote link** ("View in
  IdentityHub") pointing to `<frontend>/?project=<KEY>`, so a user reading the
  Jira ticket can jump straight back into the NHI platform (deep-linked to the
  project). It's added **best-effort** — a link failure never undoes a
  successfully created ticket. Combined with the `identityhub` label, this gives
  a bidirectional reference: app→Jira (the issue link) and Jira→app (the remote
  link).

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
- **Jira tokens**: encrypted at rest via **HashiCorp Vault's Transit engine**
  by default — the encryption key never leaves Vault and never enters this
  process; we store only the self-describing `vault:v1:…` ciphertext. A `local`
  backend (AES-256-GCM, fresh 96-bit nonce per record, key from
  `APP_ENCRYPTION_KEY`) is available for Vault-free runs and the test suite.
  Either way the plaintext token exists only transiently in memory, just long
  enough to build the Basic-auth header for a Jira request. See the design
  decision below.
- **API keys**: high-entropy random `ih_live_…` values; only a SHA-256 hash and
  a short display prefix are stored. Plaintext is returned exactly once.
- **Sessions**: opaque server-side ids in `httpOnly` + `SameSite=Lax` cookies,
  `Secure` in production; stored in Redis with a TTL, revocable by deleting the key.
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
| GET | `/auth/config` | Which login mode is active (`oidc_enabled`) — drives the login UI |
| POST | `/auth/register` | Create account, start session (password mode only; `403` under SSO) |
| POST | `/auth/login` | Log in (password mode only; `403` under SSO) |
| GET | `/auth/oidc/login` | Begin SSO — redirects to the IdP (OIDC mode only) |
| GET | `/auth/oidc/callback` | IdP redirect target — establishes the session |
| POST | `/auth/logout` | Log out (revoke session) |
| GET | `/auth/me` | Current user + Jira-connected flag |
| POST | `/jira/connect` | Verify & store Jira credentials |
| GET | `/jira/connection` | Current connection metadata |
| DELETE | `/jira/connection` | Disconnect Jira |
| GET | `/jira/projects` | List projects in the workspace |
| POST | `/findings` | Create a finding ticket |
| GET | `/findings?project_key=…&limit=…` | App-created tickets; omit `project_key` for all projects |
| GET | `/findings/{issue_key}` | Full detail for one finding (for the in-app detail page) |
| POST | `/api-keys` | Create an API key (plaintext shown once) |
| GET | `/api-keys` | List keys (prefix + metadata only) |
| DELETE | `/api-keys/{id}` | Revoke a key |
| GET | `/digest/subscriptions` | Projects this user subscribed to the blog digest |
| PUT | `/digest/subscriptions` | Replace this user's digest project set |

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
  "resource": "svc-deploy-prod",         // NHI context → description
  "category": "Stale service account",
  "environment": "aws-prod",
  "last_activity": "2026-03-01"        // date (YYYY-MM-DD)
}
```

Response (both endpoints) returns the created issue: `jira_issue_key`,
`jira_issue_url`, `title`, `project_key`, `labels`, `created_at`.

---

## NHI Blog Digest (bonus)

A periodic worker that fetches the latest post from `oasis.security/blog`,
summarizes it with a free LLM, and files a Jira ticket — `app/digest/`.

**Configure (per user):** in the app, **Report → NHI Blog Digest**, tick the
project(s) you want digest tickets filed into. Stored in `digest_subscriptions`.

**Run the worker:**
```bash
docker compose --profile digest up --build
```

**Design:**
- **Per-user subscriptions, each user's own identity.** Targets aren't a
  deployment-level setting — every user opts in by choosing project(s) in the UI,
  and the worker files each ticket under **that user's** encrypted Jira
  connection (decrypted via the same Vault/AES backend). Fully multi-tenant.
- **Separate worker container, shared codebase.** It reuses the existing
  `jira_client`, `crypto`, `models`, `config`, and Redis but runs as its own
  process — a scheduled batch job shouldn't share the API's lifecycle, and a
  single worker avoids duplicate runs if the API is scaled to many replicas.
- **Periodic.** A resilient loop runs, then sleeps `DIGEST_INTERVAL_SECONDS`
  (default daily); a failed run is logged and retried next interval rather than
  killing the loop. The post is fetched and summarized **once per cycle**, then
  filed across all subscriptions.
- **Free, provider-agnostic LLM.** Summarization speaks the OpenAI-compatible
  `chat/completions` shape, so it works with any provider by config: it defaults
  to a bundled **Ollama** (local, free, no API key — the model is auto-pulled on
  first run), and you can point `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY` at a free
  hosted endpoint (Groq, Gemini, OpenRouter) instead. No paid dependency.
- **Dedup per (user, project).** The last-posted URL is stored in Redis keyed by
  user+project, so each subscribed project receives a given post exactly once.
- **Blog fetch is resilient:** tries RSS/Atom feeds first, falls back to scraping
  the listing page.

**Future hardening (dedup).** The current dedup (a Redis marker per
`(user, project)` holding the last-posted URL) is correct for a single worker
with a live Redis, but could be strengthened:
- **Durable dedup state.** Redis here has no persistence volume, so a Redis
  restart drops the markers (and sessions) — the next cycle could re-file the
  current post once. Enable Redis AOF/RDB persistence (or move the marker to a
  durable store) to survive restarts.
- **Atomic check-and-set for multiple workers.** With a single worker the
  check-then-create-then-set sequence can't race. If the digest were scaled to
  more than one replica, two could both see "pending" and double-file; making
  the marker write a `SET key value NX` (first writer wins) closes that.
- **Jira-side idempotency.** The strongest guard, surviving any Redis loss, is
  to also query Jira before creating (JQL for an existing `nhi-blog-digest`
  ticket whose description references the post URL) and skip if found.

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
