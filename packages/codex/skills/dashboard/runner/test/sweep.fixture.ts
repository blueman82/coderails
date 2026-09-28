import { beforeEach, afterEach } from "vitest";

import { mkdtempSync, rmSync, mkdirSync, writeFileSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import type { DashboardConfig } from "@coderails/dashboard-lib";

let root: string, queueDir: string, processingDir: string, archiveDir: string, quarantineDir: string, runsDir: string, vaultNotesDir: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "sweep-test-"));
  queueDir = join(root, "queue");
  processingDir = join(root, "processing");
  archiveDir = join(root, "archive");
  quarantineDir = join(root, "quarantine");
  runsDir = join(root, "runs");
  vaultNotesDir = join(root, "dashboard-runs");
  mkdirSync(queueDir, { recursive: true });
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

const config: DashboardConfig = {
  repos: [], wikiPaths: [],
  buttons: [
    { name: "wiki-lint", label: "WIKI LINT", command: "$coderails-codex:wiki-lint", cwd: "/tmp", profile: "read-only" },
  ],
};

function writeIntent(runId: string, body: unknown) {
  writeFileSync(join(queueDir, `${runId}.json`), JSON.stringify(body));
}

export { root, queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config, writeIntent };
