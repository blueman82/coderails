import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// Mirrors queue.ts's closed-set validation discipline exactly: an
// out-of-vocabulary or missing `state` is rejected, never defaulted, and any
// unreadable/malformed file degrades to "skip this entry", never throws.
// Schema per docs/coderails/specs' sidecar contract (builds/<hash>/state.json,
// schemaVersion 1) — verified against the shipped run-builder.sh's actual
// jq -n state.json writes (skills/dashboard/scripts/run-builder.sh), not just
// the design doc's sketch.
export interface BuildEntry {
  schemaVersion: number;
  hash: string;
  state: "claimed" | "queued" | "running" | "pr_open" | "failed";
  pid?: number;
  startedAt?: number;
  claudeVersion?: string;
  prUrl?: string;
  failureReason?: string;
  stderrTail?: string;
  heartbeatAgeMs?: number;
}

const VALID_STATES: BuildEntry["state"][] = ["claimed", "queued", "running", "pr_open", "failed"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseBuildEntry(raw: unknown): Omit<BuildEntry, "heartbeatAgeMs"> | undefined {
  if (!isRecord(raw)) return undefined;
  if (typeof raw.schemaVersion !== "number") return undefined;
  if (typeof raw.hash !== "string") return undefined;
  if (typeof raw.state !== "string" || !VALID_STATES.includes(raw.state as BuildEntry["state"])) {
    return undefined;
  }
  const entry: Omit<BuildEntry, "heartbeatAgeMs"> = {
    schemaVersion: raw.schemaVersion,
    hash: raw.hash,
    state: raw.state as BuildEntry["state"],
  };
  if (typeof raw.pid === "number") entry.pid = raw.pid;
  if (typeof raw.startedAt === "number") entry.startedAt = raw.startedAt;
  if (typeof raw.claudeVersion === "string") entry.claudeVersion = raw.claudeVersion;
  if (typeof raw.prUrl === "string") entry.prUrl = raw.prUrl;
  if (typeof raw.failureReason === "string") entry.failureReason = raw.failureReason;
  if (typeof raw.stderrTail === "string") entry.stderrTail = raw.stderrTail;
  return entry;
}

// Lists `<buildsDir>/<hash>/state.json`, parsing each as a BuildEntry, and
// attaches heartbeatAgeMs from the sibling heartbeat touch-file's mtime when
// present (absent while a build is still "claimed", pre-"running"). A
// missing dir, an unreadable per-build dir, or a file that fails JSON.parse
// or shape validation contributes nothing for that entry — never throws.
export function collectBuilds(buildsDir: string): BuildEntry[] {
  let names: string[];
  try {
    names = readdirSync(buildsDir);
  } catch {
    return [];
  }

  const entries: BuildEntry[] = [];
  for (const name of names) {
    const stateFile = join(buildsDir, name, "state.json");
    let parsed: Omit<BuildEntry, "heartbeatAgeMs"> | undefined;
    try {
      const raw: unknown = JSON.parse(readFileSync(stateFile, "utf-8"));
      parsed = parseBuildEntry(raw);
    } catch {
      continue; // unreadable dir, missing state.json, or malformed JSON — skip, not fatal
    }
    if (!parsed) continue;

    let heartbeatAgeMs: number | undefined;
    try {
      const hbStat = statSync(join(buildsDir, name, "heartbeat"));
      // Clamp to 0: filesystem mtime resolution/clock skew can put a
      // just-written file's mtime microseconds ahead of Date.now(), which
      // would otherwise produce a meaningless negative age.
      heartbeatAgeMs = Math.max(0, Date.now() - hbStat.mtimeMs);
    } catch {
      // no heartbeat file yet (e.g. still "claimed", not yet "running") — leave undefined
    }
    entries.push({ ...parsed, ...(heartbeatAgeMs !== undefined ? { heartbeatAgeMs } : {}) });
  }
  return entries;
}
