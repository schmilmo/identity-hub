import { useState, type FormEvent } from "react";
import { api, ApiError, type JiraConnection } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import Alert from "./Alert";

// Connect form when no workspace is linked; summary + disconnect when one is.
export default function JiraConnectionPanel({
  connection,
  onChange,
}: {
  connection: JiraConnection | null;
  onChange: () => void;
}) {
  const { refresh } = useAuth();
  const [siteUrl, setSiteUrl] = useState("");
  const [jiraEmail, setJiraEmail] = useState("");
  const [apiToken, setApiToken] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function connect(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api.connectJira(siteUrl, jiraEmail, apiToken);
      setApiToken("");
      await refresh();
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!confirm("Disconnect this Jira workspace?")) return;
    setBusy(true);
    try {
      await api.disconnectJira();
      await refresh();
      onChange();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not disconnect.");
    } finally {
      setBusy(false);
    }
  }

  if (connection) {
    return (
      <div className="card">
        <div className="card-head">
          <h2>Jira workspace</h2>
          <span className="badge badge-ok">Connected</span>
        </div>
        <dl className="kv">
          <div>
            <dt>Site</dt>
            <dd>{connection.site_url}</dd>
          </div>
          <div>
            <dt>Account</dt>
            <dd>{connection.jira_email}</dd>
          </div>
        </dl>
        <button className="btn-ghost danger" onClick={disconnect} disabled={busy}>
          Disconnect
        </button>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>Connect Jira</h2>
      </div>
      <p className="muted">
        Paste a{" "}
        <a
          href="https://id.atlassian.com/manage-profile/security/api-tokens"
          target="_blank"
          rel="noreferrer"
        >
          Personal API Token
        </a>{" "}
        from Atlassian. Your token is encrypted before it is stored.
      </p>
      <form onSubmit={connect}>
        <label>
          Site URL
          <input
            placeholder="your-site.atlassian.net"
            value={siteUrl}
            onChange={(e) => setSiteUrl(e.target.value)}
            required
          />
        </label>
        <label>
          Jira email
          <input
            type="email"
            placeholder="you@example.com"
            value={jiraEmail}
            onChange={(e) => setJiraEmail(e.target.value)}
            required
          />
        </label>
        <label>
          API token
          <input
            type="password"
            placeholder="••••••••••••"
            value={apiToken}
            onChange={(e) => setApiToken(e.target.value)}
            required
          />
        </label>
        <Alert kind="error">{error}</Alert>
        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? "Verifying…" : "Connect"}
        </button>
      </form>
    </div>
  );
}
