import { useEffect, useState } from "react";
import { api, ApiError, type FindingTicket } from "../api/client";
import Alert from "./Alert";

const MARKER = "identityhub";

// The 10 most recent app-created tickets for the selected project, read live
// from Jira (filtered by the IdentityHub marker label). `refreshKey` re-fetches
// when bumped. Because Jira's search index is eventually consistent, a freshly
// created ticket (`pending`) is merged on top until the fetch catches up.
export default function RecentTickets({
  projectKey,
  refreshKey,
  pending,
}: {
  projectKey: string;
  refreshKey: number;
  pending: FindingTicket | null;
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

  // Merge the optimistic ticket if Jira's search hasn't surfaced it yet.
  const keys = new Set(tickets.map((t) => t.jira_issue_key));
  const display =
    pending &&
    pending.project_key === projectKey &&
    !keys.has(pending.jira_issue_key)
      ? [pending, ...tickets]
      : tickets;

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

      {projectKey && !loading && display.length === 0 && !error && (
        <p className="muted">
          No findings reported through IdentityHub for {projectKey} yet.
        </p>
      )}

      {display.length > 0 && (
        <ul className="ticket-list">
          {display.map((t) => (
            <li key={t.jira_issue_key}>
              <a href={t.jira_issue_url} target="_blank" rel="noreferrer">
                <span className="ticket-key">{t.jira_issue_key}</span>
                <span className="ticket-title">{t.title}</span>
              </a>
              <div className="ticket-meta">
                <span>{new Date(t.created_at).toLocaleString()}</span>
                {t.labels
                  .filter((l) => l !== MARKER)
                  .map((l) => (
                    <span key={l} className="tag">
                      {l}
                    </span>
                  ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
