import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import type { RoutineDef } from "@coderails/dashboard-lib";

export type FailureClass =
  | "artifact-gate-failed"
  | "skill-missing"
  | "exec-error"
  | "runner-error"
  | "claude-spawn-failed";
export type RunStatus = "green" | "red";

export interface EscalationContext {
  routine: RoutineDef;
  runId: string;
  failureClass: FailureClass;
  reason: string;
  notifyImpl?: (title: string, message: string) => void;
  vaultNotesDir?: string;
}

// Exported so recoverOrphans() in sweep.ts (which has no RoutineDef to
// build a full EscalationContext from) can drive the same notification
// channel escalate() uses, rather than re-implementing it.
export function defaultNotify(title: string, message: string): void {
  // Under vitest, suppress the real notification. Any test that drives a
  // failure path without passing its own notifyImpl otherwise falls through
  // to here and fires a genuine macOS notification — on 2026-07-22 a run of
  // sweep.test.ts flooded the notification centre with "Routine failed:
  // run-a/run-b" alerts naming test fixture paths, indistinguishable at a
  // glance from a real routine failure. Tests that assert on this function's
  // own body (escalate.test.ts's argv-injection test) delete process.env.VITEST
  // around the call to opt back in.
  if (process.env.VITEST) return;
  // macOS-only (osascript) — no cross-platform requirement exists for this
  // routine feature today. title/message are passed as trailing argv
  // elements (via `on run argv`), never interpolated into the AppleScript
  // source string — verified live 2026-07-07 in this worktree: a reason
  // string containing embedded double quotes and an attempted `"; do shell
  // script "..."` breakout produced a plain notification and did NOT
  // execute the injected command. Escalation reasons can originate from
  // artifact-derived text (e.g. an artifact-gate failure reason), so this
  // is a real injection surface, not just defense-in-depth.
  execFileSync("osascript", [
    "-e", "on run argv",
    "-e", "display notification (item 2 of argv) with title (item 1 of argv)",
    "-e", "end run",
    title,
    message,
  ]);
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

// Escalation itself must never throw: it runs from inside sweepOnce's
// per-intent failure boundary (see sweep.ts's try/catch), and a broken
// notification channel (e.g. osascript missing, or a bad notifyImpl) must
// not stop the run record — the vault note / run log is the one
// non-negotiable artifact. Each channel gets its own try/catch so one
// channel's failure can't take out the other.
export function escalate(ctx: EscalationContext): void {
  const notify = ctx.notifyImpl ?? defaultNotify;
  const title = `Routine failed: ${ctx.routine.name}`;
  const message = `${ctx.failureClass}: ${ctx.reason}`;

  try {
    notify(title, message);
  } catch (err) {
    console.error("escalate: notifyImpl threw, continuing:", err);
  }

  if (!ctx.vaultNotesDir) return; // no vault configured — notification-only escalation

  try {
    writeRunNote(
      ctx.vaultNotesDir,
      ctx.routine.name,
      ctx.runId,
      "red",
      `Failure class: ${ctx.failureClass}\nReason: ${ctx.reason}`
    );
  } catch (err) {
    console.error("escalate: writeRunNote threw, continuing:", err);
  }
}

export function checkForeignSkillExists(foreignSkillPath: string): boolean {
  return existsSync(foreignSkillPath);
}
