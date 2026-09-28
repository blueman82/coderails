import { afterEach, beforeEach } from "vitest";

import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from "node:fs";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { resetUsageMemo } from "../src/lib/collect/usage";

const tmpDirs: string[] = [];

function makeTmpBase(): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-usage-test-"));
  tmpDirs.push(dir);
  return dir;
}

// Real transcript lines carry an "assistant" line per streaming step, with the
// SAME message.id repeated across consecutive lines and an IDENTICAL usage
// snapshot on each repeat (confirmed against real ~/.codex/projects data) —
// summing every line overcounts; callers must dedupe by message.id first.
function assistantLine(
  id: string,
  timestamp: string,
  usage: { input_tokens: number; output_tokens: number; cache_creation_input_tokens?: number; cache_read_input_tokens?: number }
): string {
  return JSON.stringify({
    type: "assistant",
    timestamp,
    message: { id, role: "assistant", usage },
  });
}

// Writes <base>/<slug>/<file>.jsonl with the given raw lines, and sets the
// file's mtime so the mtime-prefilter (cheap skip of definitely-out-of-window
// files) doesn't exclude it in tests that need the content read.
function writeTranscript(base: string, slug: string, file: string, lines: string[], mtime: Date): void {
  const dir = join(base, slug);
  mkdirSync(dir, { recursive: true });
  const path = join(dir, file);
  writeFileSync(path, lines.join("\n") + (lines.length ? "\n" : ""));
  utimesSync(path, mtime, mtime);
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

beforeEach(() => {
  resetUsageMemo();
});

export { makeTmpBase, assistantLine, writeTranscript };
