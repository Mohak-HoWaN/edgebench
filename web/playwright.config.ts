import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { defineConfig } from "@playwright/test";

const PORT = 8765;
const VITE_PORT = 5173;
const python =
  process.platform === "win32"
    ? path.resolve("..", ".venv", "Scripts", "python.exe")
    : path.resolve("..", ".venv", "bin", "python");
if (!fs.existsSync(python)) {
  throw new Error(
    `The server's Python was not found at ${python}. Create the virtual environment first (README, "Run it").`,
  );
}

// Default: the real server serving the built app, with a throw-away data folder.
// E2E_DEV=1: the Vite dev server in front of the same API, which runs React in StrictMode (effects run twice).
const dev = process.env.E2E_DEV === "1";

// This file is loaded again in every worker process. The main process picks the folder and passes it on through the
// environment; only it clears folders left behind by earlier runs.
if (!process.env.EDGEBENCH_E2E_DIR) {
  for (const entry of fs.readdirSync(os.tmpdir())) {
    if (!entry.startsWith("edgebench-e2e-")) continue;
    try {
      fs.rmSync(path.join(os.tmpdir(), entry), { recursive: true, force: true, maxRetries: 3 });
    } catch {
      /* still locked by a stray process: leave it, it is only a throw-away folder */
    }
  }
  process.env.EDGEBENCH_E2E_DIR = path.join(os.tmpdir(), `edgebench-e2e-${String(process.pid)}`);
}
const dataDir = process.env.EDGEBENCH_E2E_DIR;
const api = {
  command: `"${python}" -m edgebench`,
  url: `http://127.0.0.1:${String(PORT)}/api/health`,
  reuseExistingServer: false,
  timeout: 60_000,
  env: {
    EDGEBENCH_PORT: String(PORT),
    EDGEBENCH_DATA_DIR: dataDir,
    // Browser tests use the server's stand-in converter (no torch needed) told to produce one failure, one missing package
    // and one output that differs from PyTorch, so a single upload shows every state the grid can be in.
    EDGEBENCH_CONVERTER_PYTHON: python,
    FAKE_ULTRALYTICS_FILE: path.join(dataDir, "ultralytics.txt"), // the stand-in converter claims the version written here
    EDGEBENCH_CONVERTER_DIR: path.resolve("..", "server", "tests", "fake_converter"),
    FAKE_BEHAVIOR:
      "ncnn_fp16=fail,openvino_fp16=mismatch,ncnn_fp32=unavailable,torchscript=verifyfail",
    ...(dev ? {} : { EDGEBENCH_WEB_DIST: path.resolve("dist") }),
  },
};

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${String(dev ? VITE_PORT : PORT)}`,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  webServer: dev
    ? [
        api,
        {
          command: `npx vite --host 127.0.0.1 --port ${String(VITE_PORT)} --strictPort`,
          url: `http://127.0.0.1:${String(VITE_PORT)}`,
          reuseExistingServer: false,
          timeout: 60_000,
          env: { EDGEBENCH_SERVER: `http://127.0.0.1:${String(PORT)}` },
        },
      ]
    : [api],
});
