import { defineConfig } from "@playwright/test";

// E2E tests assume:
//   - backend running at http://localhost:8000 (uvicorn app.main:app)
//   - frontend running at http://localhost:5173 (npm run dev)
// See README for the manual steps to start both servers.

// If PW_CHROME_PATH is set, use that system Chromium executable (useful in sandboxed
// environments where `playwright install` cannot reach the download CDN).
const executablePath = process.env.PW_CHROME_PATH || undefined;

export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  use: {
    baseURL: process.env.BASE_URL || "http://localhost:5173",
    headless: true,
    launchOptions: executablePath ? { executablePath } : {},
  },
});
