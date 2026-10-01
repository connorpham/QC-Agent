import { defineConfig } from "@playwright/test";
import { BACKEND_URL, FRONTEND_URL, backendEnv } from "./e2e/env";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: process.env.CI ? [["line"], ["html", { open: "never" }]] : "list",
  globalSetup: "./e2e/global-setup.ts",
  use: { baseURL: FRONTEND_URL, trace: "retain-on-failure" },
  webServer: [
    {
      name: "backend",
      command: "bash e2e/backend.sh",
      url: `${BACKEND_URL}/api/v1/health`,
      env: backendEnv,
      reuseExistingServer: false,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      name: "frontend",
      command: "pnpm exec next start -p 3001", // built by `pnpm e2e` with BACKEND_URL=…:8001
      url: FRONTEND_URL,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
