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
// both layers genuinely share; the in-memory cache below is purely a
// same-process optimization to avoid a disk read on every request — the
// file, not the cache, is the real source of truth across layers.
const DEFAULT_TOKEN_DIR = join(homedir(), ".claude", "coderails-dashboard");

function tokenFilePath(dir: string = DEFAULT_TOKEN_DIR): string {
  return join(dir, "run-token");
}

// Keyed by dir rather than a single variable — production only ever calls this with the
// default dir, but keying by dir keeps the cache honest (a call for a different dir always
// reads/writes that dir's own file, never a different dir's cached value).
const cachedTokensByDir = new Map<string, string>();

export function getRunToken(dir: string = DEFAULT_TOKEN_DIR): string {
  const cached = cachedTokensByDir.get(dir);
  if (cached) return cached;

  const path = tokenFilePath(dir);
  try {
    const existing = readFileSync(path, "utf-8").trim();
    if (existing) {
      cachedTokensByDir.set(dir, existing);
      return existing;
    }
  } catch {
    // no token file yet — mint and persist one below
  }

  const minted = mintToken();
  // 0o700/0o600: this is a credential (the run-auth secret, see mintToken's comment) — unlike
  // runs.jsonl/lock files, it must not be world- or group-readable. mkdirSync's mode only takes
  // effect when it actually creates the dir (a no-op on an existing dir, same as elsewhere in
  // this file), so an existing ~/.claude/coderails-dashboard/ with looser perms isn't tightened
  // retroactively — acceptable since that directory holds no other secrets today.
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  // "wx" (exclusive create) closes the same race two worker processes
  // starting simultaneously would otherwise hit: if another process won the
  // race and already wrote the file between our read and write, re-read
  // its value instead of clobbering it with a second, different token.
  let token: string;
  try {
    writeFileSync(path, minted, { flag: "wx", mode: 0o600 });
    token = minted;
  } catch {
    token = readFileSync(path, "utf-8").trim();
  }
  cachedTokensByDir.set(dir, token);
  return token;
}
