import { useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../auth/AuthContext";
import { api, apiErrorMessage, oidcLoginUrl } from "../api/client";
import Alert from "../components/Alert";

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // null = still loading the auth config
  const [oidcEnabled, setOidcEnabled] = useState<boolean | null>(null);

  useEffect(() => {
    api
      .authConfig()
      .then((c) => setOidcEnabled(c.oidc_enabled))
      .catch(() => setOidcEnabled(false));
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
    } catch (err) {
      setError(apiErrorMessage(err, "Something went wrong. Please try again."));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="centered">
      <div className="card auth-card">
        <div className="brand brand-lg">
          <span className="logo">◆</span> IdentityHub
        </div>
        <p className="muted subtitle">
          Report NHI findings to your Jira workspace.
        </p>

        {oidcEnabled === null ? (
          <p className="muted">Loading…</p>
        ) : oidcEnabled ? (
          <div className="sso">
            <p className="muted">
              Sign in with your organization's identity provider.
            </p>
            <a className="btn-primary sso-btn" href={oidcLoginUrl()}>
              Log in with SSO
            </a>
          </div>
        ) : (
          <>
            <div className="tabs">
              <button
                className={mode === "login" ? "tab active" : "tab"}
                onClick={() => {
                  setMode("login");
                  setError("");
                }}
              >
                Log in
              </button>
              <button
                className={mode === "register" ? "tab active" : "tab"}
                onClick={() => {
                  setMode("register");
                  setError("");
                }}
              >
                Create account
              </button>
            </div>

            <form onSubmit={onSubmit}>
              <label>
                Email
                <input
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete={
                    mode === "login" ? "current-password" : "new-password"
                  }
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={mode === "register" ? 8 : undefined}
                  required
                />
              </label>
              {mode === "register" && <p className="hint">At least 8 characters.</p>}

              <Alert kind="error">{error}</Alert>

              <button className="btn-primary" type="submit" disabled={submitting}>
                {submitting
                  ? "Please wait…"
                  : mode === "login"
                    ? "Log in"
                    : "Create account"}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
