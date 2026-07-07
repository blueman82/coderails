import { execFile as execFileReal } from "node:child_process";
import { existsSync } from "node:fs";

export interface ExecResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

type ExecFileFn = (
  command: string,
  args: readonly string[],
  options: { cwd: string },
  callback: (error: Error | null, stdout: string, stderr: string) => void
) => unknown;

export interface ExecOptions {
  claudePath?: string;
  execFileImpl?: ExecFileFn;
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
  const claudePath = opts?.claudePath ?? resolveClaudePath();
  const execFileImpl = opts?.execFileImpl ?? (execFileReal as unknown as ExecFileFn);

  return new Promise((resolve) => {
    execFileImpl(claudePath, argv, { cwd }, (error, stdout, stderr) => {
      const errorCode = (error as { code?: unknown } | null)?.code;
      const exitCode = !error ? 0 : typeof errorCode === "number" ? errorCode : 1;
      resolve({ exitCode, stdout, stderr });
    });
  });
}
