import { execFile as execFileReal } from "node:child_process";
import { existsSync } from "node:fs";

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
    execFileImpl(claudePath, argv, { cwd, timeout: timeoutMs, killSignal: "SIGKILL" }, (error, stdout, stderr) => {
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
  });
}
