import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

// Mirrors queue.ts's closed-set validation discipline exactly: an
// out-of-vocabulary or missing `state` is rejected, never defaulted, and any
// unreadable/malformed file degrades to "skip this entry", never throws.
// This is the frozen sidecar contract (builds/<hash>/state.json,
// schemaVersion 1) — verified against the shipped run-builder.sh's actual
// jq -n state.json writes (skills/dashboard/scripts/run-builder.sh).
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
  // Absolute epoch-ms mtime of the heartbeat touch-file (not a pre-computed
  // age): a relative "age as of collection time" would freeze at its
  // last-collected value if the build dies without triggering any further
  // fs.watch event (e.g. SIGKILL/power-loss skips run-builder.sh's EXIT
  // trap, so the heartbeat simply stops being touched and nothing else in
  // the builds dir changes to re-trigger a collect). An absolute timestamp
  // lets the client recompute staleness against its own live clock on every
  // render instead of trusting a value that can go stale itself.
  heartbeatAt?: number;
  // Coarse build phase the builder self-reports by writing one word to the
  // sibling `phase` touch-file (builds/<hash>/phase). The wrapper spawns
  // claude as one call and can't see inside it, so only the builder knows
  // its phase; it's closed-set-validated here (same discipline as `state`)
  // so an out-of-vocabulary or malformed word is dropped, never rendered.
  phase?: BuildPhase;
}

export type BuildPhase = "authoring" | "testing" | "pushing" | "opening_pr";

const VALID_STATES: BuildEntry["state"][] = ["claimed", "queued", "running", "pr_open", "failed"];
const VALID_PHASES: BuildPhase[] = ["authoring", "testing", "pushing", "opening_pr"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseBuildEntry(raw: unknown): Omit<BuildEntry, "heartbeatAt"> | undefined {
  if (!isRecord(raw)) return undefined;
  if (typeof raw.schemaVersion !== "number") return undefined;
  if (typeof raw.hash !== "string") return undefined;
  if (typeof raw.state !== "string" || !VALID_STATES.includes(raw.state as BuildEntry["state"])) {
    return undefined;
  }
  const entry: Omit<BuildEntry, "heartbeatAt"> = {
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
// attaches heartbeatAt from the sibling heartbeat touch-file's mtime when
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
    let parsed: Omit<BuildEntry, "heartbeatAt"> | undefined;
    try {
      const raw: unknown = JSON.parse(readFileSync(stateFile, "utf-8"));
      parsed = parseBuildEntry(raw);
    } catch {
      continue; // unreadable dir, missing state.json, or malformed JSON — skip, not fatal
    }
    if (!parsed) continue;

    let heartbeatAt: number | undefined;
    try {
      const hbStat = statSync(join(buildsDir, name, "heartbeat"));
      heartbeatAt = hbStat.mtimeMs;
    } catch {
      // no heartbeat file yet (e.g. still "claimed", not yet "running") — leave undefined
    }

    let phase: BuildPhase | undefined;
    try {
      const raw = readFileSync(join(buildsDir, name, "phase"), "utf-8").trim();
      if ((VALID_PHASES as string[]).includes(raw)) phase = raw as BuildPhase;
      // an out-of-set or malformed phase word is dropped, never defaulted
    } catch {
      // no phase file yet — leave undefined
    }

    entries.push({
      ...parsed,
      ...(heartbeatAt !== undefined ? { heartbeatAt } : {}),
      ...(phase !== undefined ? { phase } : {}),
    });
  }
  return entries;
}
