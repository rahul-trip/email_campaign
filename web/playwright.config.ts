import { defineConfig } from "@playwright/test";

// The server is Python: a real app and worker on a throwaway database with fake vendors.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:8765", trace: "retain-on-failure" },
  webServer: {
    command: "cd .. && uv run python -m scripts.e2e_server",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
