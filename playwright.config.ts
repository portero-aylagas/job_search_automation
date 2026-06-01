import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: {
    timeout: 5_000
  },
  use: {
    baseURL: "http://127.0.0.1:5175",
    trace: "on-first-retry"
  },
  webServer: {
    command: "npm run frontend:dev -- --port 5175 --strictPort",
    url: "http://127.0.0.1:5175",
    reuseExistingServer: true,
    timeout: 60_000
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] }
    }
  ]
});
