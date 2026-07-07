// EMPIRICAL CHECK (per preflight-report.md, hooks-under-`claude -p` is
// runtime-only): verified 2026-07-07 inside this worktree by running
// `claude -p "State only the words BOOTSTRAP_HOOK_FIRED if your context
// includes injected coderails bootstrap content..." --allowedTools Read`
// and separately `claude -p "Run the bash command: echo
// hello-from-hook-test" --allowedTools Bash --append-system-prompt "Report
// any hook-injected stderr/output you observe verbatim..."`.
// Result: SessionStart, UserPromptSubmit, and Stop hooks DO fire under
// `claude -p` non-interactive. The first invocation printed exactly
// `BOOTSTRAP_HOOK_FIRED`, confirming the coderails plugin's own
// SessionStart hook (inject_bootstrap.sh, which injects the
// using-coderails skill) ran. The second invocation's response showed the
// Stop-hook chain (check_confidence_labels.sh) and UserPromptSubmit hooks
// ([ctx] injection) both fired and visibly influenced the agent's own
// output.
//
// PreToolUse hooks were separately probed (2026-07-07, this worktree, a
// disposable scratch git repo) and found NOT to fire under `claude -p`:
// with `.claude/test_command` set to `exit 1` (test_gate.sh's own opt-in
// trigger, verified to return exit 1/deny when the identical stdin is
// piped to the script directly), `claude -p "Run the bash command: git
// commit -m '...'"` committed successfully — the gate never blocked it.
// This means routine runs executed by this sweeper do NOT get the same
// PreToolUse-hook safety net (test_gate, enforce_pr_workflow) an
// interactive session gets; only the SessionStart/UserPromptSubmit/Stop
// hooks above are confirmed to apply. A routine whose skill runs `git
// commit` or `git push` is not protected by test_gate/enforce_pr_workflow
// the way an interactive session would be.

import { readdirSync, readFileSync, renameSync, mkdirSync, existsSync, statSync } from "node:fs";
import { join, basename } from "node:path";
import { randomBytes } from "node:crypto";
import { parseIntent } from "@coderails/dashboard-lib";
import type { DashboardConfig, RoutineDef } from "@coderails/dashboard-lib";
import type { ButtonDef } from "../../app/src/lib/config.ts";
import { buildArgv } from "../../app/src/lib/argv.ts";
import { runClaude } from "./exec.ts";
import { appendRun, type RunRecord } from "./runlog.ts";
import { checkArtifact } from "./artifactGate.ts";
import { escalate, checkForeignSkillExists, writeRunNote, defaultNotify } from "./escalate.ts";

export interface SweepOptions {
  queueDir: string;
  processingDir: string;
  archiveDir: string;
  quarantineDir: string;
  config: DashboardConfig;
  runsDir?: string;
  vaultNotesDir?: string;
  runClaudeImpl?: typeof runClaude;
  notifyImpl?: (title: string, message: string) => void;
}

export interface SweepResult {
  claimed: number;
  succeeded: number;
  failed: number;
  quarantined: number;
}

// A file left in processing/ older than this was claimed by a sweep that
// crashed before archiving/quarantining it (a healthy sweep processes an
// intent in seconds to minutes, well under this). A fresh file may belong
// to a concurrently-running sweep and must be left alone.
export const ORPHAN_THRESHOLD_MS = 60 * 60 * 1000;

function ensureDirs(opts: SweepOptions): void {
  for (const dir of [opts.processingDir, opts.archiveDir, opts.quarantineDir]) {
    mkdirSync(dir, { recursive: true, mode: 0o700 });
  }
}

function findButton(config: DashboardConfig, name: string): ButtonDef | undefined {
  return config.buttons.find((b) => b.name === name);
}

// Matches either a routine named identically to the button, or a routine
// whose buttonRef resolves to it — mirrors seed.ts's resolveButton(), which
// accepts both paths when producing the intent in the first place. Without
// the buttonRef arm, a buttonRef-named routine (RoutineDef.name !==
// ButtonDef.name) seeds and executes correctly but silently loses its
// artifact gate, escalation, and vault run note here (C4).
function findRoutine(config: DashboardConfig, name: string): RoutineDef | undefined {
  return (config.routines ?? []).find((r) => r.name === name || r.buttonRef === name);
}

// Best-effort: each recovery step is individually guarded so a failure
// recovering one orphan can't crash recovery of the rest, or the sweep
// itself (mirrors the per-intent boundary below).
function recoverOrphans(opts: SweepOptions): void {
  let files: string[];
  try {
    files = readdirSync(opts.processingDir).filter((f) => f.endsWith(".json"));
  } catch {
    return;
  }

  for (const file of files) {
    const processingPath = join(opts.processingDir, file);
    try {
      const stat = statSync(processingPath);
      if (Date.now() - stat.mtimeMs <= ORPHAN_THRESHOLD_MS) continue; // may belong to a concurrent sweep

      try {
        renameSync(processingPath, join(opts.quarantineDir, file));
      } catch {
        continue; // couldn't move it — leave it for the next sweep to retry
      }

      const runId = randomBytes(8).toString("hex");
      const buttonName = basename(file, ".json");
      const reason = "orphaned in processing/ (stale claim, likely crashed sweep)";

      try {
        appendRun(
          {
            runId,
            button: buttonName,
            argv: [],
            cwd: "",
            profile: "read-only",
            startedAt: stat.mtimeMs,
            endedAt: Date.now(),
            exitCode: 1,
            outputPath: "",
          },
          { runsDir: opts.runsDir }
        );
      } catch {
        // best effort — the quarantine move above already happened
      }

      // Called directly rather than via escalate() — escalate() takes a
      // full RoutineDef, but an orphan's intent file may not even parse, so
      // there's no RoutineDef to construct. notify + (if configured) a
      // vault note are the same two channels escalate() drives, just
      // without requiring routine metadata this recovery path doesn't have.
      try {
        (opts.notifyImpl ?? defaultNotify)(
          `Routine failed: ${buttonName}`,
          `runner-error: ${reason}`
        );
      } catch (err) {
        console.error("recoverOrphans: notifyImpl threw, continuing:", err);
      }

      if (opts.vaultNotesDir) {
        try {
          writeRunNote(opts.vaultNotesDir, buttonName, runId, "red", `Failure class: runner-error\nReason: ${reason}`);
        } catch (err) {
          console.error("recoverOrphans: writeRunNote threw, continuing:", err);
        }
      }
    } catch {
      continue; // statSync failed (e.g. file vanished) — nothing to recover
    }
  }
}

export async function sweepOnce(opts: SweepOptions): Promise<SweepResult> {
  ensureDirs(opts);
  recoverOrphans(opts);
  const runClaudeImpl = opts.runClaudeImpl ?? runClaude;

  const result: SweepResult = { claimed: 0, succeeded: 0, failed: 0, quarantined: 0 };

  if (!existsSync(opts.queueDir)) return result;
  const files = readdirSync(opts.queueDir).filter((f) => f.endsWith(".json"));

  for (const file of files) {
    const queuePath = join(opts.queueDir, file);
    const processingPath = join(opts.processingDir, file);

    // Atomic same-fs rename claims the intent — a racing sweeper's rename
    // fails because the source is gone (see dashboard-lib README's
    // "Lifecycle" section for the full contract). This claim step stays
    // outside the per-intent boundary below: losing a claim race isn't a
    // failure of this intent, there's simply nothing here for this sweeper
    // to process.
    try {
      renameSync(queuePath, processingPath);
    } catch {
      continue; // another sweeper instance claimed it first
    }
    result.claimed++;

    // Per-intent failure boundary (B1): ANY uncaught exception while
    // processing a claimed intent — a malformed buildArgv input, an
    // appendRun write failure, anything — must not crash the sweep and
    // strand every intent queued after this one. On any throw here, the
    // file is best-effort quarantined, a best-effort finish run record is
    // appended, and a best-effort "runner-error" escalation fires, then the
    // loop moves on. Each recovery step is individually try/caught so a
    // failure in recovery itself can't crash recovery.
    try {
      let intent;
      try {
        const raw = JSON.parse(readFileSync(processingPath, "utf-8"));
        intent = parseIntent(raw);
      } catch {
        renameSync(processingPath, join(opts.quarantineDir, file));
        result.quarantined++;
        continue;
      }

      const button = findButton(opts.config, intent.button);
      if (!button) {
        renameSync(processingPath, join(opts.quarantineDir, file));
        result.quarantined++;
        continue;
      }

      const argv = buildArgv(button, intent.input);
      const startedAt = Date.now();
      const outputRunId = randomBytes(8).toString("hex");
      const startRecord: RunRecord = {
        runId: outputRunId,
        button: button.name,
        argv,
        cwd: button.cwd,
        profile: button.profile,
        startedAt,
        outputPath: join(opts.runsDir ?? "", `${outputRunId}.log`),
      };
      appendRun(startRecord, { runsDir: opts.runsDir });

      const routine = findRoutine(opts.config, button.name);

      if (routine?.foreignSkillPath && !checkForeignSkillExists(routine.foreignSkillPath)) {
        result.failed++;
        escalate({
          routine,
          runId: outputRunId,
          failureClass: "skill-missing",
          reason: `Referenced skill not found at ${routine.foreignSkillPath}`,
          notifyImpl: opts.notifyImpl,
          vaultNotesDir: opts.vaultNotesDir,
        });
        renameSync(processingPath, join(opts.archiveDir, file));
        continue;
      }

      const execResult = await runClaudeImpl(argv, button.cwd);
      appendRun({ ...startRecord, endedAt: Date.now(), exitCode: execResult.exitCode }, { runsDir: opts.runsDir });

      if (execResult.spawnFailure) {
        // Distinct from a routine's own non-zero exit ("exec-error"): the
        // claude binary was never found or execFile itself failed to spawn
        // it (B4) — "claude-spawn-failed" for both. A timeout DID spawn and
        // ran, it just didn't finish in time, so it keeps "exec-error" as
        // its failure class but the reason says "timeout" explicitly,
        // per spawnFailureReason's wording in exec.ts.
        result.failed++;
        if (routine) {
          escalate({
            routine,
            runId: outputRunId,
            failureClass: execResult.spawnFailure === "timeout" ? "exec-error" : "claude-spawn-failed",
            reason: execResult.spawnFailureReason ?? execResult.spawnFailure,
            notifyImpl: opts.notifyImpl,
            vaultNotesDir: opts.vaultNotesDir,
          });
        }
      } else if (execResult.exitCode !== 0) {
        result.failed++;
        if (routine) {
          escalate({
            routine,
            runId: outputRunId,
            failureClass: "exec-error",
            reason: `claude exited with code ${execResult.exitCode}`,
            notifyImpl: opts.notifyImpl,
            vaultNotesDir: opts.vaultNotesDir,
          });
        }
      } else if (routine) {
        const artifactResult = checkArtifact(routine.expectedArtifact, {
          date: new Date().toISOString().slice(0, 10),
          runId: outputRunId,
          vault: (opts.config.wikiPaths ?? [])[0] ?? "",
        });
        if (artifactResult.passed) {
          result.succeeded++;
          if (opts.vaultNotesDir) {
            writeRunNote(opts.vaultNotesDir, routine.name, outputRunId, "green", "succeeded");
          }
        } else {
          result.failed++;
          escalate({
            routine,
            runId: outputRunId,
            failureClass: "artifact-gate-failed",
            reason: artifactResult.reason,
            notifyImpl: opts.notifyImpl,
            vaultNotesDir: opts.vaultNotesDir,
          });
        }
      } else {
        result.succeeded++; // non-routine (button-triggered) run: exit code alone gates success
      }

      renameSync(processingPath, join(opts.archiveDir, file));
    } catch (err) {
      result.failed++;
      const reason = err instanceof Error ? err.message : String(err);

      try {
        renameSync(processingPath, join(opts.quarantineDir, file));
      } catch {
        // best effort — processingPath may already be gone if the failure
        // happened after the archive/quarantine rename itself
      }

      try {
        appendRun(
          {
            runId: randomBytes(8).toString("hex"),
            button: basename(file, ".json"),
            argv: [],
            cwd: "",
            profile: "read-only",
            startedAt: Date.now(),
            endedAt: Date.now(),
            exitCode: 1,
            outputPath: "",
          },
          { runsDir: opts.runsDir }
        );
      } catch {
        // best effort — the file is already quarantined regardless
      }

      try {
        const routine = findRoutine(opts.config, basename(file, ".json"));
        if (routine) {
          escalate({
            routine,
            runId: randomBytes(8).toString("hex"),
            failureClass: "runner-error",
            reason,
            notifyImpl: opts.notifyImpl,
            vaultNotesDir: opts.vaultNotesDir,
          });
        } else {
          (opts.notifyImpl ?? defaultNotify)(`Routine failed: ${basename(file, ".json")}`, `runner-error: ${reason}`);
        }
      } catch (escalationErr) {
        console.error("sweepOnce: escalation for a caught intent failure itself threw, continuing:", escalationErr);
      }
    }
  }

  return result;
}
