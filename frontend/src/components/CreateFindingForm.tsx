import { useState, type FormEvent, type KeyboardEvent } from "react";
import {
  api,
  ApiError,
  PRIORITIES,
  type FindingTicket,
  type JiraProject,
} from "../api/client";
import Alert from "./Alert";

// Create an NHI finding ticket. The project field is a datalist input so the
// user can either pick from their workspace projects or type a key directly
// ("selects / writes a Jira project"). Beyond title/description it supports
// custom labels, priority, a due date, and NHI-specific context fields.
export default function CreateFindingForm({
  projects,
  projectKey,
  onProjectKeyChange,
  onCreated,
}: {
  projects: JiraProject[];
  projectKey: string;
  onProjectKeyChange: (key: string) => void;
  onCreated: (ticket: FindingTicket) => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [labels, setLabels] = useState<string[]>([]);
  const [labelInput, setLabelInput] = useState("");
  const [priority, setPriority] = useState("");
  const [dueDate, setDueDate] = useState("");
  // NHI context
  const [resource, setResource] = useState("");
  const [category, setCategory] = useState("");
  const [environment, setEnvironment] = useState("");
  const [lastActivity, setLastActivity] = useState("");

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState(false);

  function addLabel() {
    // Jira labels can't contain spaces; mirror the backend normalization.
    const cleaned = labelInput.trim().replace(/\s+/g, "-");
    if (cleaned && !labels.includes(cleaned)) {
      setLabels([...labels, cleaned]);
    }
    setLabelInput("");
  }

  function onLabelKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addLabel();
    }
  }

  function reset() {
    setTitle("");
    setDescription("");
    setLabels([]);
    setLabelInput("");
    setPriority("");
    setDueDate("");
    setResource("");
    setCategory("");
    setEnvironment("");
    setLastActivity("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSuccess("");
    setBusy(true);
    try {
      const ticket = await api.createFinding({
        project_key: projectKey,
        title,
        description,
        labels,
        priority: priority || null,
        due_date: dueDate || null,
        resource: resource || null,
        category: category || null,
        environment: environment || null,
        last_activity: lastActivity || null,
      });
      setSuccess(`Created ${ticket.jira_issue_key}.`);
      reset();
      onCreated(ticket);
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
          <select
            value={projectKey}
            onChange={(e) => onProjectKeyChange(e.target.value)}
            required
            disabled={projects.length === 0}
          >
            {projects.length === 0 ? (
              <option value="">No projects found in your workspace</option>
            ) : (
              <>
                <option value="" disabled>
                  Select a project…
                </option>
                {projects.map((p) => (
                  <option key={p.key} value={p.key}>
                    {p.key} — {p.name}
                  </option>
                ))}
              </>
            )}
          </select>
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
            rows={4}
          />
        </label>

        <div className="field-row">
          <label className="grow">
            Priority
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="">— none —</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label className="grow">
            Due date
            <input
              type="date"
              value={dueDate}
              onChange={(e) => setDueDate(e.target.value)}
            />
          </label>
        </div>

        <label>
          Labels
          <input
            placeholder="Type a label and press Enter (e.g. aws, prod)"
            value={labelInput}
            onChange={(e) => setLabelInput(e.target.value)}
            onKeyDown={onLabelKeyDown}
            onBlur={addLabel}
          />
        </label>
        <div className="chips">
          <span className="chip chip-fixed" title="Added automatically by IdentityHub">
            identityhub
          </span>
          {labels.map((l) => (
            <span key={l} className="chip">
              {l}
              <button
                type="button"
                className="chip-x"
                onClick={() => setLabels(labels.filter((x) => x !== l))}
                aria-label={`Remove ${l}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>

        <details className="nhi-context">
          <summary>NHI context (optional)</summary>
          <p className="hint">
            Added to the ticket description — no portable native Jira fields exist
            for these.
          </p>
          <div className="field-row">
            <label className="grow">
              Affected resource
              <input
                placeholder="svc-deploy-prod"
                value={resource}
                onChange={(e) => setResource(e.target.value)}
              />
            </label>
            <label className="grow">
              Category
              <input
                placeholder="Stale service account"
                value={category}
                onChange={(e) => setCategory(e.target.value)}
              />
            </label>
          </div>
          <div className="field-row">
            <label className="grow">
              Environment
              <input
                placeholder="aws-prod"
                value={environment}
                onChange={(e) => setEnvironment(e.target.value)}
              />
            </label>
            <label className="grow">
              Last activity
              <input
                placeholder="2026-03-01"
                value={lastActivity}
                onChange={(e) => setLastActivity(e.target.value)}
              />
            </label>
          </div>
        </details>

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
