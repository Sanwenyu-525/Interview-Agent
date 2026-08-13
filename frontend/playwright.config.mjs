import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

// 后端 server 位于仓库根目录，webServer 的 cwd 需指回项目根。
const rootDir = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  webServer: [
    {
      command: "python -m interview_agent.server",
      cwd: rootDir,
      url: "http://127.0.0.1:8000/health",
      // 空 DB 让后端使用 InMemory 存储，避免浏览器回归污染本地 SQLite。
      env: { ...process.env, INTERVIEW_AGENT_DB: "" },
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
    },
  ],
});
