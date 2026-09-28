import { beforeEach, afterEach } from "vitest";

import { mkdtempSync, rmSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "artifact-gate-test-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

export { dir };
