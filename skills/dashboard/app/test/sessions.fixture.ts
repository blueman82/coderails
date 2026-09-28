import { afterEach } from "vitest";

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

const LOOP_FIXTURES = join(__dirname, "fixtures/projects/loops");

const tmpDirs: string[] = [];

function makeTmpBase(): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-sessions-test-"));
  tmpDirs.push(dir);
  return dir;
}

// Creates <base>/<slug>/<file> with its mtime set to `now - ageMs`.
function writeSessionFile(base: string, slug: string, ageMs: number, now: number): void {
  const dir = join(base, slug);
  mkdirSync(dir, { recursive: true });
  const file = join(dir, "session.jsonl");
  writeFileSync(file, "{}\n");
  const mtime = new Date(now - ageMs);
  utimesSync(file, mtime, mtime);
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

export { LOOP_FIXTURES, makeTmpBase, writeSessionFile };
