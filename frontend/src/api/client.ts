// Typed client for the IdentityHub backend.
//
// Every request sends credentials (the session cookie). Errors are normalized
// into ApiError carrying the backend's `detail` message, so the UI can show
// the clear, meaningful errors the backend already produces.

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
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

export const PRIORITIES = ["Highest", "High", "Medium", "Low", "Lowest"] as const;

export interface CreateFindingPayload {
  project_key: string;
  title: string;
  description?: string;
  labels?: string[];
  priority?: string | null;
  due_date?: string | null; // YYYY-MM-DD
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
  recentFindings: (projectKey: string) =>
    request<FindingTicket[]>(
      "GET",
      `/findings?project_key=${encodeURIComponent(projectKey)}`,
    ),

  // api keys
  listApiKeys: () => request<ApiKey[]>("GET", "/api-keys"),
  createApiKey: (name: string) =>
    request<CreatedApiKey>("POST", "/api-keys", { name }),
  revokeApiKey: (id: string) => request<void>("DELETE", `/api-keys/${id}`),
};
