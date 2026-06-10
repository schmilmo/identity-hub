// Typed client for the IdentityHub backend.
//
// Every request sends credentials (the session cookie). Errors are normalized
// into ApiError carrying the backend's `detail` message, so the UI can show
// the clear, meaningful errors the backend already produces.

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

// Full URL for the OIDC login redirect (a top-level browser navigation, not a
// fetch — the backend 302s to the IdP).
export function oidcLoginUrl(): string {
  return `${API_BASE}/auth/oidc/login`;
}

export interface AuthConfig {
  oidc_enabled: boolean;
  login_url: string | null;
}

export class ApiError extends Error {
  status: number;
  // Stable discriminant: `instanceof` is unreliable across module identities
  // (e.g. under the Vite dev server's HMR, where two copies of this class can
  // exist). Code should use isApiError()/apiErrorMessage() instead.
  readonly isApiError = true as const;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** HMR-safe type guard — checks the discriminant, not just the prototype. */
export function isApiError(e: unknown): e is ApiError {
  return (
    e instanceof ApiError ||
    (typeof e === "object" &&
      e !== null &&
      (e as { isApiError?: boolean }).isApiError === true)
  );
}

/** The server's `detail` message if this was an API error, else a fallback. */
export function apiErrorMessage(e: unknown, fallback: string): string {
  return isApiError(e) ? e.message : fallback;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 204) {
    return undefined as T;
  }

  let data: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok) {
    const detail =
      (data && typeof data === "object" && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : null) ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, detail);
  }

  return data as T;
}

// ---- Types mirror the backend Pydantic schemas ----
export interface User {
  id: string;
  email: string;
  jira_connected: boolean;
}

export interface JiraConnection {
  site_url: string;
  jira_email: string;
  connected_at: string;
  last_verified_at: string | null;
}

export interface JiraProject {
  key: string;
  name: string;
}

export interface FindingTicket {
  jira_issue_key: string;
  jira_issue_url: string;
  title: string;
  project_key: string;
  labels: string[];
  created_at: string;
}

export interface FindingDetail {
  jira_issue_key: string;
  jira_issue_url: string;
  title: string;
  description: string;
  labels: string[];
  priority: string | null;
  status: string | null;
  assignee: string | null;
  created_at: string | null;
  resource: string | null;
  category: string | null;
  environment: string | null;
  last_activity: string | null;
}

export const PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"] as const;

export interface CreateFindingPayload {
  project_key: string;
  title: string;
  description?: string;
  labels?: string[];
  priority?: string | null;
  resource?: string | null;
  category?: string | null;
  environment?: string | null;
  last_activity?: string | null;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface CreatedApiKey extends ApiKey {
  api_key: string;
}

export const api = {
  // auth
  register: (email: string, password: string) =>
    request<User>("POST", "/auth/register", { email, password }),
  login: (email: string, password: string) =>
    request<User>("POST", "/auth/login", { email, password }),
  logout: () => request<void>("POST", "/auth/logout"),
  me: () => request<User>("GET", "/auth/me"),
  authConfig: () => request<AuthConfig>("GET", "/auth/config"),

  // jira
  connectJira: (site_url: string, jira_email: string, api_token: string) =>
    request<JiraConnection>("POST", "/jira/connect", {
      site_url,
      jira_email,
      api_token,
    }),
  getJiraConnection: () => request<JiraConnection>("GET", "/jira/connection"),
  disconnectJira: () => request<void>("DELETE", "/jira/connection"),
  listProjects: () => request<JiraProject[]>("GET", "/jira/projects"),

  // findings
  createFinding: (payload: CreateFindingPayload) =>
    request<FindingTicket>("POST", "/findings", payload),
  // 10 most recent for one project (dashboard panel).
  recentFindings: (projectKey: string) =>
    request<FindingTicket[]>(
      "GET",
      `/findings?limit=10&project_key=${encodeURIComponent(projectKey)}`,
    ),
  // Browse findings; omit projectKey for all projects.
  listFindings: (projectKey?: string | null, limit = 50) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (projectKey) p.set("project_key", projectKey);
    return request<FindingTicket[]>("GET", `/findings?${p.toString()}`);
  },
  getFinding: (key: string) =>
    request<FindingDetail>("GET", `/findings/${encodeURIComponent(key)}`),

  // api keys
  listApiKeys: () => request<ApiKey[]>("GET", "/api-keys"),
  createApiKey: (name: string) =>
    request<CreatedApiKey>("POST", "/api-keys", { name }),
  revokeApiKey: (id: string) => request<void>("DELETE", `/api-keys/${id}`),
};
