import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import type { RoutineDef } from "@coderails/dashboard-lib";

export type FailureClass = "artifact-gate-failed" | "skill-missing" | "exec-error";
export type RunStatus = "green" | "red";

export interface EscalationContext {
  routine: RoutineDef;
  runId: string;
  failureClass: FailureClass;
  reason: string;
  notifyImpl?: (title: string, message: string) => void;
  vaultNotesDir?: string;
}

function defaultNotify(title: string, message: string): void {
  // macOS-only (osascript) — no cross-platform requirement exists for this
  // routine feature today.
  execFileSync("osascript", ["-e", `display notification "${message}" with title "${title}"`]);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

// Shared by both the failure path (escalate(), status "red") and the
// success path (sweep.ts's routine-gating block, status "green") so a
// routine's vault note always shows its full green/red run history in one
// place, per F5's status: green|red design — extracted rather than
// duplicated in sweep.ts (see WU4 Task 4.6's self-review note).
export function writeRunNote(
  vaultNotesDir: string,
  routineName: string,
  runId: string,
  status: RunStatus,
  detail: string
): void {
  mkdirSync(vaultNotesDir, { recursive: true });
  const notePath = join(vaultNotesDir, `${routineName}.md`);
  const runSection = `\n## [${todayIso()}] run ${runId} — ${status}\n\n${detail}\n`;

  if (existsSync(notePath)) {
    const existing = readFileSync(notePath, "utf-8");
    writeFileSync(notePath, existing + runSection);
  } else {
    const frontmatter = `---\ntitle: "${routineName}"\ntype: routine-run\ncreated: ${todayIso()}\nlast_updated: ${todayIso()}\nstatus: ${status}\n---\n`;
    writeFileSync(notePath, frontmatter + runSection);
  }
}

export function escalate(ctx: EscalationContext): void {
  const notify = ctx.notifyImpl ?? defaultNotify;
  const title = `Routine failed: ${ctx.routine.name}`;
  const message = `${ctx.failureClass}: ${ctx.reason}`;
  notify(title, message);

  if (!ctx.vaultNotesDir) return; // no vault configured — notification-only escalation

  writeRunNote(
    ctx.vaultNotesDir,
    ctx.routine.name,
    ctx.runId,
    "red",
    `Failure class: ${ctx.failureClass}\nReason: ${ctx.reason}`
  );
}

export function checkForeignSkillExists(foreignSkillPath: string): boolean {
  return existsSync(foreignSkillPath);
}
