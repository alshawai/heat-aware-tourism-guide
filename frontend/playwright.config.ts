import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:8000",
    trace: "on-first-retry",
  },
  webServer: {
    command:
      ".venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000",
    cwd: "..",
    env: {
      ...process.env,
      ALLOW_LIVE: "false",
    },
    url: "http://127.0.0.1:8000/health",
    reuseExistingServer: !process.env.CI,
  },
});
