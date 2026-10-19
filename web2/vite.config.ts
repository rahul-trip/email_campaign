import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The new app runs on :5174 (the old one keeps :5173) and forwards /api to the Python server.
// API_TARGET points it at another server, such as the browser-test server on :8765.
const target = process.env.API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5174, strictPort: true, proxy: { "/api": target } },
  // Never inline assets as data: URLs. The server's Content-Security-Policy allows fonts only
  // from itself, so an inlined font subset would be blocked in production.
  build: { assetsInlineLimit: 0 },
});
