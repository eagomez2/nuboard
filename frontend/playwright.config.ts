import { defineConfig } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Serves a freshly generated demo workspace (with a live run) on port 6071.
// Needs the Python package installed: `uv sync` (or `pip install -e '.[viewer]'`) in the repo root.
const python = process.env.PYTHON ?? '../.venv/bin/python';
const dir = join(tmpdir(), `nb-e2e-${process.pid}`);

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://localhost:6071',
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  webServer: {
    command: `${python} -m nuboard demo ${dir} --up --port 6071 --edit-artifacts`,
    url: 'http://localhost:6071/api/info',
    timeout: 60_000,
    reuseExistingServer: false,
  },
});
