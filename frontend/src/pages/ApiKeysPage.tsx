import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError, type ApiKey, type CreatedApiKey } from "../api/client";
import Alert from "../components/Alert";

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<CreatedApiKey | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    try {
      setKeys(await api.listApiKeys());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load keys.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const key = await api.createApiKey(name);
      setCreated(key);
      setName("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create key.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    if (!confirm("Revoke this key? External systems using it will stop working."))
      return;
    try {
      await api.revokeApiKey(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not revoke key.");
    }
  }

  return (
    <div className="api-keys">
      <div className="card">
        <div className="card-head">
          <h2>API keys</h2>
        </div>
        <p className="muted">
          Keys let external systems (scanners, CI/CD) create findings via{" "}
          <code>POST /api/v1/findings</code>. They act on your Jira connection.
        </p>

        <form className="inline-form" onSubmit={create}>
          <input
            placeholder="Key name, e.g. ci-prod-scanner"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={100}
            required
          />
          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? "Generating…" : "Generate key"}
          </button>
        </form>

        <Alert kind="error">{error}</Alert>

        {created && (
          <div className="key-reveal">
            <Alert kind="success">
              Copy this key now — it won’t be shown again.
            </Alert>
            <code className="key-value">{created.api_key}</code>
            <button
              className="btn-ghost"
              onClick={() => navigator.clipboard?.writeText(created.api_key)}
            >
              Copy
            </button>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Your keys</h2>
        </div>
        {keys.length === 0 ? (
          <p className="muted">No API keys yet.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Prefix</th>
                <th>Created</th>
                <th>Last used</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {keys.map((k) => (
                <tr key={k.id} className={k.revoked_at ? "revoked" : ""}>
                  <td>{k.name}</td>
                  <td>
                    <code>{k.key_prefix}…</code>
                  </td>
                  <td>{new Date(k.created_at).toLocaleDateString()}</td>
                  <td>
                    {k.last_used_at
                      ? new Date(k.last_used_at).toLocaleString()
                      : "—"}
                  </td>
                  <td>
                    {k.revoked_at ? (
                      <span className="badge badge-muted">Revoked</span>
                    ) : (
                      <span className="badge badge-ok">Active</span>
                    )}
                  </td>
                  <td>
                    {!k.revoked_at && (
                      <button
                        className="btn-ghost danger"
                        onClick={() => revoke(k.id)}
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
