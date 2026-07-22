import { execFile as execFileReal } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

export interface ExecResult {
  exitCode: number;
  stdout: string;
  stderr: string;
  // Set only for the two spawn-time failure modes this module distinguishes
  // from a routine's own non-zero exit (a plain "exec-error"): a timeout
  // (the process was killed because it ran longer than timeoutMs) or a
  // spawn failure (resolveClaudePath() found no claude binary, or execFile
  // itself failed to spawn — e.g. ENOENT cwd). Absent for a normal
  // completed run, successful or not.
  spawnFailure?: "timeout" | "spawn-failed";
  spawnFailureReason?: string;
}

type ExecFileFn = (
  command: string,
  args: readonly string[],
  options: { cwd: string; timeout: number; killSignal: NodeJS.Signals },
  callback: (error: Error | null, stdout: string, stderr: string) => void
) => unknown;

// 30 minutes: generous enough for a routine that shells out to a full
// coderails skill run, but a hard ceiling so a hung claude process can't
// wedge the sweeper indefinitely — the per-intent loop needs runClaude to
// eventually settle one way or another.
export const DEFAULT_TIMEOUT_MS = 30 * 60 * 1000;

export interface ExecOptions {
  claudePath?: string;
  execFileImpl?: ExecFileFn;
  timeoutMs?: number;
  resolveClaudePathImpl?: () => string;
  // When set, the run's final stdout+stderr is written here once the
  // execFile callback fires (on every settle path — success, non-zero exit,
  // timeout, or ENOENT-style spawn failure). Without this, runClaude
  // returned its output in-memory only, so a scheduled routine that ran RED
  // left NO transcript at the outputPath the sweeper had already recorded in
  // the run ledger (the sync-docs-nightly RED-with-no-transcript case) —
  // making the failure undiagnosable. This mirrors route.ts, which persists
  // the run's output to its outputPath.
  outputPath?: string;
}

// Best-effort persistence of a settled run's output. execFile buffers each
// stream separately (there is no per-chunk interleaving to preserve, unlike
// route.ts's live-streaming spawn path), so stdout and stderr are simply
// concatenated. Plain text is written deliberately — NOT stream-json — since
// the sole consumer here is a human diagnosing a failed routine, for whom
// readable text beats a JSON-lines stream. A write failure is logged and
// swallowed: losing the transcript must never mask or discard the ExecResult
// the caller needs to gate the run.
function persistOutput(outputPath: string, stdout: string, stderr: string): void {
  try {
    mkdirSync(dirname(outputPath), { recursive: true });
    writeFileSync(outputPath, stdout + stderr);
  } catch (err) {
    console.error("[exec] failed to persist run output", { outputPath, err });
  }
}

// launchd invokes this binary with NO PATH set (verified via `launchctl
// print gui/$UID` on this machine 2026-07-06 — only SSH_AUTH_SOCK is set),
// so a bare "claude" command string would fail to spawn under launchd even
// though it works fine under an interactive shell. This resolves to the
// one absolute path confirmed to exist on this machine; a future
// multi-machine deployment would need this to become configurable, but no
// such requirement exists today (YAGNI).
const KNOWN_CLAUDE_PATHS = ["/Users/harrison/.local/bin/claude", "/opt/homebrew/bin/claude"];

export function resolveClaudePath(): string {
  for (const path of KNOWN_CLAUDE_PATHS) {
    if (existsSync(path)) return path;
  }
  throw new Error(
    `resolveClaudePath: no claude binary found at any known path (${KNOWN_CLAUDE_PATHS.join(", ")})`
  );
}

export function runClaude(argv: string[], cwd: string, opts?: ExecOptions): Promise<ExecResult> {
  let claudePath: string;
  try {
    claudePath = opts?.claudePath ?? (opts?.resolveClaudePathImpl ?? resolveClaudePath)();
  } catch (err) {
    // No claude binary found at any known path — distinct from a routine's
    // own non-zero exit ("exec-error"): this never got to spawn at all.
    return Promise.resolve({
      exitCode: 1,
      stdout: "",
      stderr: "",
      spawnFailure: "spawn-failed",
      spawnFailureReason: err instanceof Error ? err.message : String(err),
    });
  }

  const execFileImpl = opts?.execFileImpl ?? (execFileReal as unknown as ExecFileFn);
  const timeoutMs = opts?.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  return new Promise((resolve) => {
    const options = { cwd, timeout: timeoutMs, killSignal: "SIGKILL" as NodeJS.Signals };
    const child = execFileImpl(claudePath, argv, options, (error, stdout, stderr) => {
      // Persist first, before any branch returns: whatever the outcome
      // (timeout, spawn-failed, non-zero exit, or success), the stdout/stderr
      // captured so far is exactly what a human needs to diagnose the run.
      if (opts?.outputPath) persistOutput(opts.outputPath, stdout, stderr);
      if (error && (error as { killed?: boolean; signal?: string }).signal === "SIGKILL") {
        resolve({
          exitCode: 1,
          stdout,
          stderr,
          spawnFailure: "timeout",
          spawnFailureReason: `claude process exceeded timeout of ${timeoutMs}ms and was killed`,
        });
        return;
      }
      const errorCode = (error as { code?: unknown } | null)?.code;
      if (error && typeof errorCode === "string") {
        // execFile failed to spawn the process at all (e.g. ENOENT cwd) —
        // distinct from the process starting and exiting non-zero.
        resolve({
          exitCode: 1,
          stdout,
          stderr,
          spawnFailure: "spawn-failed",
          spawnFailureReason: `${errorCode}: ${(error as Error).message}`,
        });
        return;
      }
      const exitCode = !error ? 0 : typeof errorCode === "number" ? errorCode : 1;
      resolve({ exitCode, stdout, stderr });
    });
    // Close the child's stdin immediately. execFile gives the child a stdin
    // PIPE that this parent never writes to and never closes, so the claude
    // CLI blocks waiting on it and after 3s emits "Warning: no stdin data
    // received in 3s, proceeding without it" — a mandatory ~3s stall on every
    // scheduled routine run. Passing `stdio: ["ignore", ...]` does NOT work:
    // execFile silently drops the stdio option and always pipes all three fds
    // (verified 2026-07-22 — child.stdin is still an open pipe). Ending the
    // write side sends EOF, so the CLI proceeds at once. stdout/stderr stay
    // piped and untouched — they are the ExecResult and the persisted
    // transcript. Optional-chained throughout because the injectable
    // execFileImpl seam used by the tests returns no child object.
    (child as { stdin?: { end?: () => void } | null } | undefined)?.stdin?.end?.();
  });
}
