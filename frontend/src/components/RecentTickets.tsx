import { useEffect, useState } from "react";
import { api, ApiError, type FindingTicket } from "../api/client";
import Alert from "./Alert";

// The 10 most recent app-created tickets for the selected project. Each row
// links to the Jira issue in a new tab. `refreshKey` re-fetches when bumped
// (e.g. after a new ticket is created).
export default function RecentTickets({
  projectKey,
  refreshKey,
}: {
  projectKey: string;
  refreshKey: number;
}) {
  const [tickets, setTickets] = useState<FindingTicket[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectKey) {
      setTickets([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .recentFindings(projectKey)
      .then((rows) => {
        if (!cancelled) setTickets(rows);
      })
      .catch((err) => {
        if (!cancelled)
          setError(
            err instanceof ApiError ? err.message : "Could not load tickets.",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectKey, refreshKey]);

  return (
    <div className="card">
      <div className="card-head">
        <h2>Recent findings</h2>
        {projectKey && <span className="badge">{projectKey}</span>}
      </div>

      {!projectKey && (
        <p className="muted">Choose a project to see its recent findings.</p>
      )}
      <Alert kind="error">{error}</Alert>
      {loading && <p className="muted">Loading…</p>}

      {projectKey && !loading && tickets.length === 0 && !error && (
        <p className="muted">
          No findings reported through IdentityHub for {projectKey} yet.
        </p>
      )}

      {tickets.length > 0 && (
        <ul className="ticket-list">
          {tickets.map((t) => (
            <li key={t.jira_issue_key}>
              <a href={t.jira_issue_url} target="_blank" rel="noreferrer">
                <span className="ticket-key">{t.jira_issue_key}</span>
                <span className="ticket-title">{t.title}</span>
              </a>
              <span className="ticket-meta">
                {new Date(t.created_at).toLocaleString()}
                {t.source === "api" && <span className="tag">via API</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
