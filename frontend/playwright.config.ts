import { defineConfig } from '@playwright/test';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Two freshly generated demo workspaces. Most tests run against one with no live run (port
// 6072), so no live update redraws the page while a test hovers or clicks it. Tests tagged
// @live need a run that keeps logging, and get the demo's live run (port 6071).
// Needs the Python package installed: `uv sync` (or `pip install -e .`) in the repo root.
const python = process.env.PYTHON ?? '../.venv/bin/python';
const dir = join(tmpdir(), `nb-e2e-${process.pid}`);
const live = 'http://localhost:6071';
const still = 'http://localhost:6072';

export default defineConfig({
  testDir: 'e2e',
  timeout: 30_000,
  // a test that passes only on its retry is reported as flaky instead of failing the run
  retries: 1,
  // one worker: the tests share each demo workspace, and some write to it (reports, tags)
  workers: 1,
  use: {
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  projects: [
    { name: 'still', grepInvert: /@live/, use: { baseURL: still } },
    { name: 'live', grep: /@live/, use: { baseURL: live } },
  ],
  webServer: [
    {
      command: `${python} -m nuboard demo ${dir}-still && exec ${python} -m nuboard up ${dir}-still --port 6072 --edit-artifacts`,
      url: `${still}/api/info`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
    },
    {
      command: `${python} -m nuboard demo ${dir}-live --up --port 6071 --edit-artifacts`,
      url: `${live}/api/info`,
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: 'pipe',
    },
  ],
});
