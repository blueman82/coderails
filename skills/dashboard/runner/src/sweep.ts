// EMPIRICAL CHECK (per preflight-report.md, hooks-under-`claude -p` is
// runtime-only): verified 2026-07-07 inside this worktree by running
// `claude -p "State only the words BOOTSTRAP_HOOK_FIRED if your context
// includes injected coderails bootstrap content..." --allowedTools Read`
// and separately `claude -p "Run the bash command: echo
// hello-from-hook-test" --allowedTools Bash --append-system-prompt "Report
// any hook-injected stderr/output you observe verbatim..."`.
// Result: hooks DO fire under `claude -p` non-interactive. The first
// invocation printed exactly `BOOTSTRAP_HOOK_FIRED`, confirming the
// coderails plugin's own SessionStart hook (inject_bootstrap.sh, which
// injects the using-coderails skill) ran. The second invocation's response
// showed the Stop-hook chain (check_confidence_labels.sh) and
// UserPromptSubmit hooks ([ctx] injection) both fired and visibly
// influenced the agent's own output — corroborating evidence across three
// distinct hook events (SessionStart, UserPromptSubmit, Stop), not just one.
// The hard-stop condition in Task 2.4 does NOT trigger: routine runs
// executed by this sweeper get the same hook-based safety net (test_gate,
// enforce_pr_workflow, discipline hooks) as an interactive session.

import { readdirSync, readFileSync, renameSync, mkdirSync, existsSync } from "node:fs";
import { join, basename } from "node:path";
import { randomBytes } from "node:crypto";
import { parseIntent } from "@coderails/dashboard-lib";
import type { DashboardConfig, RoutineDef } from "@coderails/dashboard-lib";
import type { ButtonDef } from "../../app/src/lib/config.ts";
import { buildArgv } from "../../app/src/lib/argv.ts";
import { runClaude } from "./exec.ts";
import { appendRun, type RunRecord } from "./runlog.ts";
import { checkArtifact } from "./artifactGate.ts";
import { escalate, checkForeignSkillExists, writeRunNote } from "./escalate.ts";

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

function ensureDirs(opts: SweepOptions): void {
  for (const dir of [opts.processingDir, opts.archiveDir, opts.quarantineDir]) {
    mkdirSync(dir, { recursive: true });
  }
}

function findButton(config: DashboardConfig, name: string): ButtonDef | undefined {
  return config.buttons.find((b) => b.name === name);
}

function findRoutine(config: DashboardConfig, name: string): RoutineDef | undefined {
  return (config.routines ?? []).find((r) => r.name === name);
}

export async function sweepOnce(opts: SweepOptions): Promise<SweepResult> {
  ensureDirs(opts);
  const runClaudeImpl = opts.runClaudeImpl ?? runClaude;

  const result: SweepResult = { claimed: 0, succeeded: 0, failed: 0, quarantined: 0 };

  if (!existsSync(opts.queueDir)) return result;
  const files = readdirSync(opts.queueDir).filter((f) => f.endsWith(".json"));

  for (const file of files) {
    const queuePath = join(opts.queueDir, file);
    const processingPath = join(opts.processingDir, file);

    // Atomic same-fs rename claims the intent — a racing sweeper's rename
    // fails because the source is gone (see dashboard-lib README's
    // "Lifecycle" section for the full contract).
    try {
      renameSync(queuePath, processingPath);
    } catch {
      continue; // another sweeper instance claimed it first
    }
    result.claimed++;

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

    if (execResult.exitCode !== 0) {
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
  }

  return result;
}
