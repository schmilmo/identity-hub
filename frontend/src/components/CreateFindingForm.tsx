import { useState, type FormEvent } from "react";
import { api, ApiError, type JiraProject } from "../api/client";
import Alert from "./Alert";

// Create an NHI finding ticket. The project field is a datalist input so the
// user can either pick from their workspace projects or type a key directly
// (Requirement: "selects / writes a Jira project").
export default function CreateFindingForm({
  projects,
  projectKey,
  onProjectKeyChange,
  onCreated,
}: {
  projects: JiraProject[];
  projectKey: string;
  onProjectKeyChange: (key: string) => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setBusy(true);
    try {
      const ticket = await api.createFinding(projectKey, title, description);
      setSuccess(`Created ${ticket.jira_issue_key}.`);
      setTitle("");
      setDescription("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create ticket.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>New NHI finding</h2>
      </div>
      <form onSubmit={submit}>
        <label>
          Project
          <input
            list="project-options"
            placeholder="e.g. NHI"
            value={projectKey}
            onChange={(e) => onProjectKeyChange(e.target.value.toUpperCase())}
            required
          />
          <datalist id="project-options">
            {projects.map((p) => (
              <option key={p.key} value={p.key}>
                {p.name}
              </option>
            ))}
          </datalist>
        </label>
        <label>
          Title
          <input
            placeholder="Stale Service Account: svc-deploy-prod"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={255}
            required
          />
        </label>
        <label>
          Description
          <textarea
            placeholder="Details about the finding…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={5}
          />
        </label>
        <Alert kind="error">{error}</Alert>
        <Alert kind="success">{success}</Alert>
        <button
          className="btn-primary"
          type="submit"
          disabled={busy || !projectKey}
        >
          {busy ? "Creating…" : "Create ticket"}
        </button>
      </form>
    </div>
  );
}
