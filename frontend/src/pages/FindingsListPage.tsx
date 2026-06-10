import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  api,
  apiErrorMessage,
  type FindingTicket,
  type JiraProject,
} from "../api/client";
import Alert from "../components/Alert";

const MARKER = "identityhub";

// Browse all IdentityHub-created findings, filterable by project (or all
// projects). Rows link to the in-app detail page, not directly to Jira.
export default function FindingsListPage() {
  const [projects, setProjects] = useState<JiraProject[]>([]);
  const [project, setProject] = useState(""); // "" = all projects
  const [findings, setFindings] = useState<FindingTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Projects for the filter dropdown (best-effort; list still works without it).
  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .listFindings(project || null, 50)
      .then((rows) => !cancelled && setFindings(rows))
      .catch(
        (err) =>
          !cancelled && setError(apiErrorMessage(err, "Could not load findings.")),
      )
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [project]);

  return (
    <div className="findings-page">
      <div className="card">
        <div className="card-head">
          <h2>Findings</h2>
          <label className="inline-filter">
            Project
            <select value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">All projects</option>
              {projects.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.key} — {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <Alert kind="error">{error}</Alert>
        {loading && <p className="muted">Loading…</p>}

        {!loading && !error && findings.length === 0 && (
          <p className="muted">
            No findings reported through IdentityHub
            {project ? ` for ${project}` : ""} yet. Create one on the{" "}
            <Link to="/">Report</Link> tab.
          </p>
        )}

        {findings.length > 0 && (
          <ul className="ticket-list">
            {findings.map((t) => (
              <li key={t.jira_issue_key}>
                <Link to={`/findings/${t.jira_issue_key}`}>
                  <span className="ticket-key">{t.jira_issue_key}</span>
                  <span className="ticket-title">{t.title}</span>
                </Link>
                <div className="ticket-meta">
                  <span className="badge">{t.project_key}</span>
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
    </div>
  );
}
