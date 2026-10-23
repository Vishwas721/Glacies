// Browser tests of the demo story (Phase 7 M9) against the real API, worker and Valkey/Redis on
// Toyville. Locally they use the installed Chrome; CI installs Playwright's Chromium.

import { defineConfig } from "@playwright/test";

import { API_PORT, GLACIES_ENV, ROOT, WEB_PORT } from "./e2e/env";

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  fullyParallel: false,
  workers: 1, // one queue and one worker: the tests share them
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    ...(process.env.CI ? {} : { channel: "chrome" }),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: `uv run uvicorn glacies.api.app:app --port ${API_PORT}`,
      cwd: ROOT,
      url: `http://localhost:${API_PORT}/api/health`,
      env: GLACIES_ENV,
      timeout: 180_000,
    },
    {
      command: `pnpm exec vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { VITE_BASEMAP: "blank", GLACIES_API_URL: `http://localhost:${API_PORT}` },
      timeout: 120_000,
    },
  ],
});
