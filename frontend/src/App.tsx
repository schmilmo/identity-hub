import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import ApiKeysPage from "./pages/ApiKeysPage";
import Layout from "./components/Layout";

export default function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="centered muted">Loading…</div>;
  }

  if (!user) {
    // Unauthenticated: only the login/register screen is reachable.
    return (
      <Routes>
        <Route path="*" element={<LoginPage />} />
      </Routes>
    );
  }

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/api-keys" element={<ApiKeysPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
