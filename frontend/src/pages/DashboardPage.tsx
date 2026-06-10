import { useCallback, useEffect, useState } from "react";
import {
  api,
  apiErrorMessage,
  type FindingTicket,
  type JiraConnection,
  type JiraProject,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import JiraConnectionPanel from "../components/JiraConnectionPanel";
import CreateFindingForm from "../components/CreateFindingForm";
import RecentTickets from "../components/RecentTickets";
import Alert from "../components/Alert";

export default function DashboardPage() {
  const { user } = useAuth();
  const [connection, setConnection] = useState<JiraConnection | null>(null);
  const [projects, setProjects] = useState<JiraProject[]>([]);
  // Honor a ?project=KEY deep link (e.g. from the "View in IdentityHub" link on
  // a Jira issue) so the dashboard opens focused on that project.
  const [projectKey, setProjectKey] = useState(
    () => new URLSearchParams(window.location.search).get("project") ?? "",
  );
  const [refreshKey, setRefreshKey] = useState(0);
  const [pending, setPending] = useState<FindingTicket | null>(null);
  const [error, setError] = useState("");

  function onCreated(ticket: FindingTicket) {
    setPending(ticket); // show immediately despite Jira's search-index lag
    setRefreshKey((k) => k + 1);
  }

  // Load connection + projects whenever the connected flag flips.
  const load = useCallback(async () => {
    setError("");
    if (!user?.jira_connected) {
      setConnection(null);
      setProjects([]);
      setProjectKey("");
      return;
    }
    try {
      const [conn, projs] = await Promise.all([
        api.getJiraConnection(),
        api.listProjects(),
      ]);
      setConnection(conn);
      setProjects(projs);
      // Default the picker to the first project for convenience.
      setProjectKey((prev) => prev || projs[0]?.key || "");
    } catch (err) {
      // Projects can fail (e.g. revoked token) even if a connection row exists.
      setError(apiErrorMessage(err, "Could not load your Jira workspace."));
      try {
        setConnection(await api.getJiraConnection());
      } catch {
        setConnection(null);
      }
    }
  }, [user?.jira_connected]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="dashboard">
      <div className="col">
        <JiraConnectionPanel connection={connection} onChange={load} />
      </div>

      {user?.jira_connected && (
        <>
          <div className="col">
            <Alert kind="error">{error}</Alert>
            <CreateFindingForm
              projects={projects}
              projectKey={projectKey}
              onProjectKeyChange={setProjectKey}
              onCreated={onCreated}
            />
          </div>
          <div className="col">
            <RecentTickets
              projectKey={projectKey}
              refreshKey={refreshKey}
              pending={pending}
            />
          </div>
        </>
      )}
    </div>
  );
}
