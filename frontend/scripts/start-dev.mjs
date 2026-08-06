import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const projectRoot = path.resolve(frontendRoot, "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const children = [];
let shuttingDown = false;

function start(command, args, options = {}) {
  const child = spawn(command, args, {
    cwd: options.cwd || frontendRoot,
    env: options.env || process.env,
    stdio: "inherit",
    shell: options.shell || false,
    windowsHide: false,
  });
  children.push(child);
  return child;
}

const backend = start(process.env.PYTHON || "python", ["-m", "interview_agent.server"], {
  cwd: projectRoot,
  env: {
    ...process.env,
    PYTHONPATH: projectRoot,
    INTERVIEW_AGENT_DB: path.join(projectRoot, "interview-agent.db"),
  },
});

const frontend = start(
  npmCommand,
  ["run", "dev", "--", "--host", "0.0.0.0", "--port", "4173", "--strictPort"],
  { shell: process.platform === "win32" },
);

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill();
  }
  setTimeout(() => process.exit(code), 250);
}

for (const child of children) {
  child.on("exit", (code) => {
    if (!shuttingDown && code && code !== 0) shutdown(code);
  });
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
