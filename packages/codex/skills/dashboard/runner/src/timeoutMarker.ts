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
  if (predicate.kind !== "last-marker") return;
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
    const last = mine[mine.length - 1];
    const runId = last ? last.run_id : ctx.runId;
    const terminal = mine.filter((row) => row.run_id === runId && TERMINAL_OUTCOMES.has(row.outcome)).pop();
    if (terminal) return { passed: terminal.outcome === "run_ok", reason: `routine_terminal:${terminal.outcome}` };
    const ts = new Date().toISOString();
    const row = {
      v: 1,
      ts,
      run_id: runId,
      routine: last ? last.routine : routine.name,
      stage: "runner",
      outcome: "run_abort",
      reason_code: "runner_exit_no_terminal",
    };
    mkdirSync(dirname(jsonl), { recursive: true });
    appendFileSync(jsonl, `${JSON.stringify(row)}\n`);
    if (writeMarker) appendFileSync(human, `${ts} ${resolveArtifactPath(predicate.failures[0], ctx)}runner_exit_no_terminal\n`);
    return { passed: false, reason: "runner_exit_no_terminal" };
  } catch (err) {
    return { passed: false, reason: `routine_log_unavailable: ${err instanceof Error ? err.message : String(err)}` };
  }
}
