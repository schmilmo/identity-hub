import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, apiErrorMessage, type FindingDetail } from "../api/client";
import Alert from "../components/Alert";

const MARKER = "identityhub";

// In-app detail for one finding, reconstructed from Jira (the source of truth).
// Shows the information captured at creation plus a button to open the Jira issue.
export default function FindingDetailPage() {
  const { key = "" } = useParams();
  const [finding, setFinding] = useState<FindingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .getFinding(key)
      .then((f) => !cancelled && setFinding(f))
      .catch(
        (err) =>
          !cancelled && setError(apiErrorMessage(err, "Could not load finding.")),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [key]);

  const context: [string, string | null | undefined][] = finding
    ? [
        ["Affected resource", finding.resource],
        ["Finding category", finding.category],
        ["Environment", finding.environment],
        ["Last activity", finding.last_activity],
      ]
    : [];
  const hasContext = context.some(([, v]) => v);

  return (
    <div className="finding-detail">
      <Link className="back-link" to="/findings">
        ← Back to findings
      </Link>

      <Alert kind="error">{error}</Alert>
      {loading && <p className="muted">Loading…</p>}

      {finding && (
        <div className="card">
          <div className="card-head detail-head">
            <div>
              <span className="ticket-key">{finding.jira_issue_key}</span>
              <h2>{finding.title}</h2>
            </div>
            <a
              className="btn-primary open-jira"
              href={finding.jira_issue_url}
              target="_blank"
              rel="noreferrer"
            >
              Open in Jira ↗
            </a>
          </div>

          <dl className="kv detail-kv">
            {finding.status && (
              <div>
                <dt>Status</dt>
                <dd>{finding.status}</dd>
              </div>
            )}
            {finding.priority && (
              <div>
                <dt>Priority</dt>
                <dd>{finding.priority}</dd>
              </div>
            )}
            {finding.assignee && (
              <div>
                <dt>Assignee</dt>
                <dd>{finding.assignee}</dd>
              </div>
            )}
            {finding.created_at && (
              <div>
                <dt>Created</dt>
                <dd>{new Date(finding.created_at).toLocaleString()}</dd>
              </div>
            )}
          </dl>

          {finding.labels.filter((l) => l !== MARKER).length > 0 && (
            <div className="chips detail-labels">
              {finding.labels
                .filter((l) => l !== MARKER)
                .map((l) => (
                  <span key={l} className="chip">
                    {l}
                  </span>
                ))}
            </div>
          )}

          <h3 className="detail-section">Description</h3>
          <pre className="description">{finding.description || "(none)"}</pre>

          {hasContext && (
            <>
              <h3 className="detail-section">NHI context</h3>
              <dl className="kv detail-kv">
                {context
                  .filter(([, v]) => v)
                  .map(([label, value]) => (
                    <div key={label}>
                      <dt>{label}</dt>
                      <dd>{value}</dd>
                    </div>
                  ))}
              </dl>
            </>
          )}
        </div>
      )}
    </div>
  );
}
