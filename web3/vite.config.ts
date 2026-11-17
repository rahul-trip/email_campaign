import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// web3, the bright redesign, runs on :5175 beside web2 (:5174) and forwards /api to the Python server.
const target = process.env.API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5175, strictPort: true, proxy: { "/api": target } },
  build: { assetsInlineLimit: 0 },
});
