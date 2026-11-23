import { defineConfig, devices } from "@playwright/test";

// Playwright E2E configuration for the NourishRelay demo stack.
// Tests run against a RUNNING stack — either the local dev stack
// (web :3000 + api :8000) or the Docker Compose stack (web :3000 only is
// published). Override the target with E2E_BASE_URL.
const config = defineConfig({
  testDir: "./tests/e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 20_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
});

export default config;
