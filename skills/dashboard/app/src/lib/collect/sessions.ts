import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

export interface SessionInfo {
  project: string;
  lastActivity: number;
  state: "active" | "idle" | "stalled";
}

export interface LoopUnit {
  key: string;
  done: boolean;
  inFlight: boolean;
  description?: string;
  pr?: number;
}

export interface LoopInfo {
  slug: string;
  // Loop title, chain: progress.json's "loop" field -> authorising_prompt_raw
  // (first 80 chars, trimmed, "…") -> slug (see readTitle below).
  title: string;
  sessionId: string;
  status: string;
  workUnitsDone: number;
  workUnitsTotal: number;
  evalsFrozen: boolean;
  // progress.json's last_updated field when it parses as a valid date, else
  // progress.json's own file mtime (see readLastUpdatedMs below).
  lastUpdatedMs: number;
  units: LoopUnit[];
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

// Non-empty string, else undefined — used for both the description/desc
// fields (description wins over the desc alias; either may be blank in a
// hand-edited progress.json).
function readNonEmptyString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() !== "" ? value : undefined;
}

// Real progress.json files use "in-progress" and (older) "doing" for the
// same in-flight state (see plan.md's LoopUnit field comment).
function readUnit(key: string, unit: Record<string, unknown>): LoopUnit {
  const status = unit.status;
  return {
    key,
    done: status === "done",
    inFlight: status === "in-progress",
    description: readNonEmptyString(unit.description) ?? readNonEmptyString(unit.desc),
    pr: typeof unit.pr === "number" ? unit.pr : undefined,
  };
}

// work_units is documented (SKILL.md) as an object keyed by unit id, each
// entry carrying at least a status. Some real progress.json files predate
// that schema and carry work_units as an array of {id, status, ...} instead.
// Accept both without throwing; anything else degrades to no units.
function readUnits(workUnits: unknown): LoopUnit[] {
  if (Array.isArray(workUnits)) {
    return workUnits
      .filter(isRecord)
      .map((unit) => readUnit(typeof unit.id === "string" ? unit.id : "", unit));
  }
  if (isRecord(workUnits)) {
    return Object.entries(workUnits)
      .filter(([, unit]) => isRecord(unit))
      .map(([key, unit]) => readUnit(key, unit as Record<string, unknown>));
  }
  return [];
}

// decisions_absorbed is documented (SKILL.md) as a chronological array of
// {phase, decision} appended oldest-first. Older progress.json files predate
// the field entirely. Same degrade-don't-throw stance as readUnits:
// non-array or non-record entries are skipped rather than raising. Returns
// the last 5 entries, newest first, formatted "<phase>: <decision>".
function readDecisions(decisionsAbsorbed: unknown): string[] {
  if (!Array.isArray(decisionsAbsorbed)) return [];
  return decisionsAbsorbed
    .filter(isRecord)
    .filter((entry) => typeof entry.phase === "string" && typeof entry.decision === "string")
    .map((entry) => `${entry.phase as string}: ${entry.decision as string}`)
    .slice(-5)
    .reverse();
}

// progress.json's "loop" field is a free-text human name (e.g. "observability-dashboard
// (sub-project 1 of agentic-os evolution)"), not present on every loop. Falls back to
// the first 80 chars of authorising_prompt_raw (trimmed, "…" appended when truncated),
// then to the dir slug when neither is present.
function readTitle(record: Record<string, unknown>, slug: string): string {
  const loop = readNonEmptyString(record.loop);
  if (loop) return loop;
  const prompt = readNonEmptyString(record.authorising_prompt_raw);
  if (prompt) {
    const trimmed = prompt.trim();
    return trimmed.length > 80 ? `${trimmed.slice(0, 80)}…` : trimmed;
  }
  return slug;
}

// last_updated is a free-text timestamp field written by the orchestrator, not
// guaranteed to parse (or be present at all) on every progress.json. Falls back
// to the file's own mtime — a crashed writer can leave mtime touched without a
// corresponding last_updated bump, but that's still a better signal than 0.
function readLastUpdatedMs(record: Record<string, unknown>, progressPath: string): number {
  const lastUpdated = typeof record.last_updated === "string" ? Date.parse(record.last_updated) : NaN;
  if (!Number.isNaN(lastUpdated)) return lastUpdated;
  try {
    return statSync(progressPath).mtimeMs;
  } catch {
    return 0;
  }
}

// Mirrors als_read_loop_evals_result (hooks/scripts/lib/loop_state_common.sh):
// GO or a justified TIER0 exemption count as frozen; NO-GO, UNJUSTIFIED,
// ABSENT, wrong scope, or malformed JSON do not. An explicit NO-GO wins over
// the tier-0 exemption, same precedence as the bash SSOT.
// Also mirrors the hook's UNSTAMPED check: GO/TIER0 additionally require a
// `.grading` stamp (post_evals.sh grade-loop's provenance record) to read as
// frozen — both `.grading.by` and `.grading.checksum` must be present AND
// non-empty, matching the bash reader's `[ -z "$stamped_by" ] || [ -z
// "$stamped_checksum" ]` check. This is presence-only — no checksum
// recomputation here, unlike the hook, since this is a display surface
// (KISS); a status edited after grading without re-stamping will still show
// frozen here even though the hook would demote it to UNSTAMPED.
function readEvalsFrozen(loopDir: string): boolean {
  const data = readJson(join(loopDir, "evals.json"));
  if (!isRecord(data)) return false;
  if (data.scope !== "loop") return false;
  const justification = typeof data.tier_justification === "string" ? data.tier_justification.trim() : "";
  if (!justification) return false;
  if (data.result === "NO-GO") return false;
  const grading = isRecord(data.grading) ? data.grading : undefined;
  const stampedBy = typeof grading?.by === "string" ? grading.by.trim() : "";
  const stampedChecksum = typeof grading?.checksum === "string" ? grading.checksum.trim() : "";
  if (!stampedBy || !stampedChecksum) return false;
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
      const progressPath = join(loopDir, "progress.json");
      const progress = readJson(progressPath);
      const record = isRecord(progress) ? progress : {};
      const units = readUnits(record.work_units);
      loops.push({
        slug,
        title: readTitle(record, slug),
        sessionId: typeof record.session_id === "string" ? record.session_id : sessionId,
        status: typeof record.status === "string" ? record.status : "",
        workUnitsDone: units.filter((u) => u.done).length,
        workUnitsTotal: units.length,
        evalsFrozen: readEvalsFrozen(loopDir),
        lastUpdatedMs: readLastUpdatedMs(record, progressPath),
        units,
        decisions: readDecisions(record.decisions_absorbed),
      });
    }
  }
  return loops;
}
