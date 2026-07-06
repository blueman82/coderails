import type { ButtonDef } from "./config";

// Tools that only read state, never mutate the filesystem or run commands —
// safe for a read-only-profile button. Verified against `claude --help`
// 2026-07-06.
export const READ_ONLY_ALLOWED_TOOLS = ["Read", "Grep", "Glob"];

// buildArgv is THE single profile→flag mapping (per Task 7 brief) — Task 13
// must reuse this, never re-implement it. `input`, when given, is appended
// as exactly one argv element after any profile flags; it is never
// concatenated into `btn.command` or any other string, so it can't inject
// additional flags or shell syntax into the spawned process.
export function buildArgv(btn: ButtonDef, input?: string): string[] {
  const argv = ["-p", btn.command];

  if (btn.profile === "read-only") {
    argv.push("--allowedTools", ...READ_ONLY_ALLOWED_TOOLS);
  } else if (btn.profile === "bypass") {
    argv.push("--dangerously-skip-permissions");
  }

  if (input !== undefined) {
    argv.push(input);
  }

  return argv;
}
