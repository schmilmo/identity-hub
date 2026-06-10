import { type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">◆</span> IdentityHub
        </div>
        <nav className="nav">
          <Link className={pathname === "/" ? "active" : ""} to="/">
            Report
          </Link>
          <Link
            className={pathname.startsWith("/findings") ? "active" : ""}
            to="/findings"
          >
            Findings
          </Link>
          <Link
            className={pathname === "/api-keys" ? "active" : ""}
            to="/api-keys"
          >
            API Keys
          </Link>
        </nav>
        <div className="user">
          <span className="muted">{user?.email}</span>
          <button className="btn-ghost" onClick={() => logout()}>
            Log out
          </button>
        </div>
      </header>
      <main className="content">{children}</main>
    </div>
  );
}
