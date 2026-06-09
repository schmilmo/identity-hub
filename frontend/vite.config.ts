import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The frontend talks to the backend cross-origin in dev (5173 -> 8000).
// CORS on the backend allows credentials from FRONTEND_ORIGIN, and the
// session cookie is SameSite=Lax (same site, different port = allowed).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
