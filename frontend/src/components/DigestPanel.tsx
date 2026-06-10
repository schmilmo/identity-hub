import { useEffect, useState } from "react";
import { api, apiErrorMessage, type JiraProject } from "../api/client";
import Alert from "./Alert";

// Lets the user opt into the NHI Blog Digest by selecting which of their Jira
// projects should receive the auto-generated digest tickets. The worker files
// under this user's own Jira connection.
export default function DigestPanel({ projects }: { projects: JiraProject[] }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    api
      .getDigestSubscriptions()
      .then((r) => setSelected(new Set(r.project_keys)))
      .catch((err) => setError(apiErrorMessage(err, "Could not load subscriptions.")))
      .finally(() => setLoading(false));
  }, []);

  function toggle(key: string) {
    setSuccess("");
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  }

  async function save() {
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      const r = await api.setDigestSubscriptions([...selected]);
      setSelected(new Set(r.project_keys));
      setSuccess("Saved.");
    } catch (err) {
      setError(apiErrorMessage(err, "Could not save subscriptions."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>NHI Blog Digest</h2>
      </div>
      <p className="muted">
        Pick the project(s) where the digest should file a ticket summarizing the
        latest Oasis NHI blog post. Tickets are created under your Jira connection.
      </p>

      {loading ? (
        <p className="muted">Loading…</p>
      ) : projects.length === 0 ? (
        <p className="muted">No projects available in your workspace.</p>
      ) : (
        <div className="digest-projects">
          {projects.map((p) => (
            <label key={p.key} className="check-row">
              <input
                type="checkbox"
                checked={selected.has(p.key)}
                onChange={() => toggle(p.key)}
              />
              <span>
                <span className="ticket-key">{p.key}</span> {p.name}
              </span>
            </label>
          ))}
        </div>
      )}

      <Alert kind="error">{error}</Alert>
      <Alert kind="success">{success}</Alert>
      <button className="btn-primary" onClick={save} disabled={busy || loading}>
        {busy ? "Saving…" : "Save digest projects"}
      </button>
    </div>
  );
}
