import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

export interface SessionInfo {
  project: string;
  lastActivity: number;
  state: "active" | "idle" | "stalled";
}

export interface LoopInfo {
  slug: string;
  // Human-readable loop name from progress.json's "loop" field; falls back to
  // `slug` when absent, blank, or non-string (see readLoopName below).
  name: string;
  sessionId: string;
  status: string;
  workUnitsDone: number;
  workUnitsTotal: number;
  evalsFrozen: boolean;
  unitTitles: { title: string; done: boolean }[];
  decisions: string[];
}

const ACTIVE_THRESHOLD_MS = 5 * 60_000;
const STALLED_THRESHOLD_MS = 60 * 60_000;

function listDirs(baseDir: string): string[] {
  try {
    return readdirSync(baseDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .map((entry) => entry.name);
  } catch {
    return [];
  }
}

// Most-recent file mtime under <baseDir>/<slug>/ (recursed one level, since
// session dirs may hold a transcript file directly or nested files).
function latestMtimeMs(dir: string): number {
  let latest = 0;
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return latest;
  }
  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      latest = Math.max(latest, latestMtimeMs(path));
    } else {
      try {
        latest = Math.max(latest, statSync(path).mtimeMs);
      } catch {
        // ignore unreadable file
      }
    }
  }
  return latest;
}

// baseDir is a ~/.claude/projects-shaped tree: <baseDir>/<slug>/ holding session
// transcript files directly or nested. Distinct from collectLoops' base below —
// same param name, different real directory tree; callers must pass each
// collector its own matching base dir.
export function collectSessions(baseDir: string, now: number): SessionInfo[] {
  const sessions: SessionInfo[] = [];
  for (const slug of listDirs(baseDir)) {
    const lastActivity = latestMtimeMs(join(baseDir, slug));
    const age = now - lastActivity;
    const state: SessionInfo["state"] =
      age < ACTIVE_THRESHOLD_MS ? "active" : age < STALLED_THRESHOLD_MS ? "idle" : "stalled";
    sessions.push({ project: slug, lastActivity, state });
  }
  return sessions;
}

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// work_units is documented (SKILL.md) as an object keyed by unit id, each
// entry carrying at least a status. Some real progress.json files predate
// that schema and carry work_units as an array of {id, status, ...} instead.
// Accept both without throwing; anything else degrades to no units.
function readUnitTitles(workUnits: unknown): { title: string; done: boolean }[] {
  if (Array.isArray(workUnits)) {
    return workUnits
      .filter(isRecord)
      .map((unit) => ({
        title: typeof unit.id === "string" ? unit.id : "",
        done: unit.status === "done",
      }));
  }
  if (isRecord(workUnits)) {
    return Object.entries(workUnits)
      .filter(([, unit]) => isRecord(unit))
      .map(([title, unit]) => ({
        title,
        done: (unit as Record<string, unknown>).status === "done",
      }));
  }
  return [];
}

// progress.json's "loop" field is a free-text human name (e.g. "observability-dashboard
// (sub-project 1 of agentic-os evolution)"), not present on every loop. Falls back to the
// dir slug when absent, blank, or not a string.
function readLoopName(record: Record<string, unknown>, slug: string): string {
  const loop = record.loop;
  if (typeof loop === "string" && loop.trim() !== "") return loop;
  return slug;
}

// Mirrors als_read_loop_evals_result (hooks/scripts/lib/loop_state_common.sh):
// GO or a justified TIER0 exemption count as frozen; NO-GO, UNJUSTIFIED,
// ABSENT, wrong scope, or malformed JSON do not.
function readEvalsFrozen(loopDir: string): boolean {
  const data = readJson(join(loopDir, "evals.json"));
  if (!isRecord(data)) return false;
  if (data.scope !== "loop") return false;
  const justification = typeof data.tier_justification === "string" ? data.tier_justification.trim() : "";
  if (!justification) return false;
  if (data.result === "GO") return true;
  if (data.tier === 0) return true;
  return false;
}

// baseDir is a ~/.claude/agentic-loop-shaped tree: <baseDir>/<slug>/<sessionId>/
// holding progress.json (+ optional sibling evals.json). Distinct from
// collectSessions' base above — see that function's comment.
export function collectLoops(baseDir: string): LoopInfo[] {
  const loops: LoopInfo[] = [];
  for (const slug of listDirs(baseDir)) {
    const projectDir = join(baseDir, slug);
    for (const sessionId of listDirs(projectDir)) {
      const loopDir = join(projectDir, sessionId);
      const progress = readJson(join(loopDir, "progress.json"));
      const record = isRecord(progress) ? progress : {};
      const unitTitles = readUnitTitles(record.work_units);
      loops.push({
        slug,
        name: readLoopName(record, slug),
        sessionId: typeof record.session_id === "string" ? record.session_id : sessionId,
        status: typeof record.status === "string" ? record.status : "",
        workUnitsDone: unitTitles.filter((u) => u.done).length,
        workUnitsTotal: unitTitles.length,
        evalsFrozen: readEvalsFrozen(loopDir),
        unitTitles,
      });
    }
  }
  return loops;
}
