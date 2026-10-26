import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";
import type { RoutineDef } from "@coderails/dashboard-lib";
import { resolveArtifactPath, type ArtifactCheckContext, type ArtifactCheckResult } from "./artifactGate.ts";

export function localDateIso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function recordTimeoutMarker(routine: RoutineDef, ctx: ArtifactCheckContext): void {
  const predicate = routine.expectedArtifact.predicate;
  if (predicate.kind !== "last-marker" || mergeAttemptState(routine, ctx) !== "none") return;
  const path = resolveArtifactPath(routine.expectedArtifact.artifactPath, ctx);
  const marker = resolveArtifactPath(predicate.failures[0], ctx);
  try {
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, `${new Date().toISOString()} ${marker}runner-timeout-kill\n`);
  } catch (err) {
    console.error("recordTimeoutMarker: failed to append terminal marker, continuing:", err);
  }
}

const TERMINAL_OUTCOMES = new Set(["run_ok", "run_abort", "run_refused"]);

interface RoutineRow {
  ts: string;
  run_id: string;
  routine: string;
  outcome: string;
  reason_code?: string;
}

function readLog(path: string): Buffer {
  try {
    return readFileSync(path);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return Buffer.alloc(0);
    throw err;
  }
}

export function routineLogBoundary(routine: RoutineDef, ctx: ArtifactCheckContext): Buffer | null {
  const human = resolveArtifactPath(routine.expectedArtifact.artifactPath, ctx);
  if (routine.expectedArtifact.predicate.kind !== "last-marker" || !human.endsWith(".log")) return null;
  return readLog(`${human.slice(0, -4)}.jsonl`);
}

function readRows(contents: Buffer): RoutineRow[] {
  const rows: RoutineRow[] = [];
  for (const line of contents.toString("utf-8").split("\n")) {
    try {
      const row = JSON.parse(line);
      if (row && typeof row.run_id === "string" && typeof row.outcome === "string") rows.push(row);
    } catch {
      // torn or blank line: not a row
    }
  }
  return rows;
}

function mergeAttemptState(routine: RoutineDef, ctx: ArtifactCheckContext): "none" | "attempt" | "unavailable" {
  const template = routine.expectedArtifact.artifactPath.replace("{date}", "active");
  const human = resolveArtifactPath(template, ctx);
  try {
    const state = JSON.parse(readFileSync(`${human.slice(0, -4)}.state.json`, "utf-8"));
    if (state.v !== 1 || state.run_id !== ctx.runId || state.routine !== routine.name) return "unavailable";
    return state.merge_attempt ? "attempt" : "none";
  } catch {
    return "unavailable";
  }
}

// Only rows appended after the caller's prelaunch boundary can establish this invocation's terminal evidence.
// The fallback appends remain unlocked against concurrent Python emits; its result still prevents false success.
export function ensureTerminalRow(
  routine: RoutineDef,
  ctx: ArtifactCheckContext,
  boundary: Buffer | null,
  writeMarker = true,
): ArtifactCheckResult {
  const predicate = routine.expectedArtifact.predicate;
  if (predicate.kind !== "last-marker" || boundary === null) return { passed: true, reason: "No routine event log" };
  const human = resolveArtifactPath(routine.expectedArtifact.artifactPath, ctx);
  const jsonl = `${human.slice(0, -4)}.jsonl`;
  try {
    const contents = readLog(jsonl);
    if (!contents.subarray(0, boundary.length).equals(boundary)) {
      return { passed: false, reason: "routine_log_changed: existing event log changed during invocation" };
    }
    const mine = readRows(contents.subarray(boundary.length));
    const own = mine.filter((row) => row.run_id === ctx.runId && row.routine === routine.name);
    const terminal = own.filter((row) => TERMINAL_OUTCOMES.has(row.outcome)).pop();
    if (terminal) {
      if (terminal.outcome !== "run_ok") return { passed: false, reason: `routine_terminal:${terminal.outcome}` };
      const marker = `run_id=${ctx.runId} run=ok`;
      const humanHasOwnSuccess = readLog(human).toString("utf-8").split("\n").some((line) => line.endsWith(marker));
      return { passed: humanHasOwnSuccess, reason: humanHasOwnSuccess ? "routine_terminal:run_ok" : "routine_human_marker_missing" };
    }
    if (own.some((row) => row.outcome === "run_incomplete" && row.reason_code === "merged_incomplete")) {
      return { passed: false, reason: "routine_merged_incomplete" };
    }
    const mergeAttempt = mergeAttemptState(routine, ctx);
    if (mergeAttempt === "unavailable") return { passed: false, reason: "routine_state_unavailable" };
    const pendingMerge = mergeAttempt === "attempt";
    const ts = new Date().toISOString();
    const row = {
      v: 1,
      ts,
      run_id: ctx.runId,
      routine: routine.name,
      stage: "runner",
      outcome: pendingMerge ? "run_incomplete" : "run_abort",
      reason_code: pendingMerge ? "merge_state_unknown" : "runner_exit_no_terminal",
    };
    mkdirSync(dirname(jsonl), { recursive: true });
    appendFileSync(jsonl, `${JSON.stringify(row)}\n`);
    if (pendingMerge) appendFileSync(human, `${ts} incomplete=merge-unknown\n`);
    else if (writeMarker) appendFileSync(human, `${ts} ${resolveArtifactPath(predicate.failures[0], ctx)}runner_exit_no_terminal\n`);
    return { passed: false, reason: pendingMerge ? "routine_merge_state_unknown" : "runner_exit_no_terminal" };
  } catch (err) {
    return { passed: false, reason: `routine_log_unavailable: ${err instanceof Error ? err.message : String(err)}` };
  }
}
