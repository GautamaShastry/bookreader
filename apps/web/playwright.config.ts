import { defineConfig, devices } from "@playwright/test";

const PORT = 4173;
const isCI = Boolean(process.env["CI"]);

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: isCI,
  retries: 0,
  reporter: [["list"], ["junit", { outputFile: "../../test-results/playwright.xml" }]],
  outputDir: "../../test-results/playwright",
  use: { baseURL: `http://127.0.0.1:${String(PORT)}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm run build && npm run preview -- --host 127.0.0.1 --port ${String(PORT)} --strictPort`,
    url: `http://127.0.0.1:${String(PORT)}`,
    reuseExistingServer: !isCI,
    timeout: 120_000,
  },
});
