import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { homedir } from "node:os";
import { join } from "node:path";
import type { PermissionProfile } from "./config";

export interface RunRecord {
  runId: string;
  button: string;
  argv: string[];
  cwd: string;
  profile: PermissionProfile;
  startedAt: number;
  endedAt?: number;
  exitCode?: number;
  outputPath: string;
}

export interface RunLogOptions {
  runsDir?: string;
}

const DEFAULT_RUNS_DIR = join(homedir(), ".claude", "coderails-dashboard", "runs");

function runsFilePath(opts?: RunLogOptions): string {
  return join(opts?.runsDir ?? DEFAULT_RUNS_DIR, "runs.jsonl");
}

// One JSONL line per call — appendRun is called once at run start and again
// at finish (with endedAt/exitCode set), so a run's history is two lines;
// readRuns folds duplicates by taking the newest line per runId.
export function appendRun(rec: RunRecord, opts?: RunLogOptions): void {
  const dir = opts?.runsDir ?? DEFAULT_RUNS_DIR;
  mkdirSync(dir, { recursive: true });
  appendFileSync(runsFilePath(opts), JSON.stringify(rec) + "\n");
}

// Reads the JSONL run log, keeping only the newest line per runId (a run's
// finish line supersedes its start line), sorted newest-first by startedAt,
// truncated to `limit`. A missing file or a malformed line degrades
// gracefully rather than throwing.
export function readRuns(limit: number, opts?: RunLogOptions): RunRecord[] {
  let raw: string;
  try {
    raw = readFileSync(runsFilePath(opts), "utf-8");
  } catch {
    return [];
  }

  const byRunId = new Map<string, RunRecord>();
  for (const line of raw.split("\n")) {
    if (!line.trim()) continue;
    try {
      const rec = JSON.parse(line) as RunRecord;
      byRunId.set(rec.runId, rec);
    } catch {
      // skip malformed line
    }
  }

  return Array.from(byRunId.values())
    .sort((a, b) => b.startedAt - a.startedAt)
    .slice(0, limit);
}

// mintToken generates a per-server-start secret. It is delivered to the
// client ONLY via server-render into the page (see Task 8) — never through
// any API response body — so an attacker who can only reach the HTTP API
// (e.g. from an unrelated browser tab, per the Origin/Host check in the run
// route) cannot recover it.
export function mintToken(): string {
  return randomBytes(32).toString("hex");
}

// The run token is persisted to a file rather than kept in a module-scope
// variable: Next.js's app router compiles Route Handlers (route.ts) and
// Server Components (page.tsx) as SEPARATE module graphs/bundler layers even
// when both target the Node.js runtime — confirmed empirically on this
// machine 2026-07-06, a shared plain-lib module-level `let cachedToken`
// still ended up as two independently-initialized copies (one per layer),
// so the token embedded in the rendered page never matched what POST
// /api/run compared against and every run 401'd. A file is the one thing
// both layers genuinely share. In-memory caching per-process is layered on
// top (getRunTokenPath's directory read only happens once per module
// instance) purely to avoid a disk read on every request; the file itself,
// not the variable, is the actual source of truth across layers.
const DEFAULT_TOKEN_DIR = join(homedir(), ".claude", "coderails-dashboard");

function tokenFilePath(dir: string = DEFAULT_TOKEN_DIR): string {
  return join(dir, "run-token");
}

let cachedToken: string | undefined;

export function getRunToken(dir: string = DEFAULT_TOKEN_DIR): string {
  if (cachedToken) return cachedToken;

  const path = tokenFilePath(dir);
  try {
    const existing = readFileSync(path, "utf-8").trim();
    if (existing) {
      cachedToken = existing;
      return cachedToken;
    }
  } catch {
    // no token file yet — mint and persist one below
  }

  const minted = mintToken();
  mkdirSync(dir, { recursive: true });
  // "wx" (exclusive create) closes the same race two worker processes
  // starting simultaneously would otherwise hit: if another process won the
  // race and already wrote the file between our read and write, re-read
  // its value instead of clobbering it with a second, different token.
  try {
    writeFileSync(path, minted, { flag: "wx" });
    cachedToken = minted;
  } catch {
    cachedToken = readFileSync(path, "utf-8").trim();
  }
  return cachedToken;
}
