import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";
import type { RoutineDef } from "@coderails/dashboard-lib";
import { resolveArtifactPath, type ArtifactCheckContext } from "./artifactGate.ts";

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

function readRows(path: string): RoutineRow[] {
  if (!existsSync(path)) return [];
  const rows: RoutineRow[] = [];
  for (const line of readFileSync(path, "utf-8").split("\n")) {
    try {
      const row = JSON.parse(line);
      if (row && typeof row.run_id === "string" && typeof row.outcome === "string") rows.push(row);
    } catch {
      // torn or blank line: not a row
    }
  }
  return rows;
}

// After a routine child exits (any exit code), the routine's JSONL event log (scripts/routine_log.py; the
// artifactPath with .log replaced by .jsonl) must hold a terminal row (run_ok, run_abort or run_refused) for the
// run. The run is the latest run_id with a row at or after startedAtMs, else the runner's own run id. If none is
// there the child ended without finishing, so append run_abort reason_code=runner_exit_no_terminal and, unless the
// caller already wrote a text marker (writeMarker false), the matching legacy `abort=` line. Only last-marker
// artifacts whose path ends in .log have this log; best-effort and non-fatal like recordTimeoutMarker. Limit: the two
// appends are not locked against a concurrent routine_log.py emit.
export function ensureTerminalRow(
  routine: RoutineDef,
  ctx: ArtifactCheckContext,
  startedAtMs: number,
  writeMarker = true,
): void {
  const predicate = routine.expectedArtifact.predicate;
  if (predicate.kind !== "last-marker") return;
  const human = resolveArtifactPath(routine.expectedArtifact.artifactPath, ctx);
  if (!human.endsWith(".log")) return;
  const jsonl = `${human.slice(0, -4)}.jsonl`;
  try {
    const since = Math.floor(startedAtMs / 1000) * 1000;
    const mine = readRows(jsonl).filter((row) => Date.parse(row.ts) >= since);
    const last = mine[mine.length - 1];
    const runId = last ? last.run_id : ctx.runId;
    if (mine.some((row) => row.run_id === runId && TERMINAL_OUTCOMES.has(row.outcome))) return;
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
  } catch (err) {
    console.error("ensureTerminalRow: failed to append terminal row, continuing:", err);
  }
}
