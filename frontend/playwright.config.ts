import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

const e2eDatabase = resolve(import.meta.dirname, "../var/e2e.sqlite3");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? "list" : [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: `rm -f "${e2eDatabase}" "${e2eDatabase}-shm" "${e2eDatabase}-wal" && SQLITE_PATH="${e2eDatabase}" bash ../dev.sh --local`,
    cwd: resolve(import.meta.dirname),
    url: "http://127.0.0.1:5173",
    reuseExistingServer: false,
    timeout: 240_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
