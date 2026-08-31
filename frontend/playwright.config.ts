import { defineConfig } from "@playwright/test";

// The suite always starts its own fixture-mode server, never adopting one, so a
// local dev server on the default port would otherwise block the whole run.
// `E2E_PORT` moves this run's server aside instead; CI keeps the default.
const port = Number(process.env.E2E_PORT ?? 8000);
const origin = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: origin,
    trace: "on-first-retry",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1280, height: 720 } } },
    {
      name: "mobile",
      use: { viewport: { width: 375, height: 812 }, isMobile: true },
    },
  ],
  webServer: {
    command: `.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port ${port}`,
    cwd: "..",
    env: {
      ...process.env,
      ALLOW_LIVE: "false",
    },
    url: `${origin}/health`,
    // Never adopt a server this config did not start. A local dev server on the
    // same port reads .env, so it can be live: reusing it would run the fixture
    // suite against billable provider calls. Failing to bind is the clearer
    // answer, and it names the port to free.
    reuseExistingServer: false,
  },
});
