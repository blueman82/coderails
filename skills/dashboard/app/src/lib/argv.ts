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
//
// Two independent layers close the flag-smuggling vector (an input value
// like "--dangerously-skip-permissions" being parsed by the claude CLI as a
// real flag instead of literal prompt text, confirmed empirically on this
// machine 2026-07-06: `claude -p "--version"` prints the version banner and
// never answers the prompt, i.e. the CLI really does parse a leading-dash
// argument as a flag): (1) input starting with "-" is rejected outright
// (throws) rather than trusting the sentinel alone; (2) a literal "--"
// end-of-options sentinel is inserted immediately before input regardless,
// confirmed on this machine 2026-07-06 to make the claude CLI treat
// everything after it as literal argument text (`claude -p "..." --
// "--dangerously-skip-permissions"` ran as a normal sandboxed prompt, no
// permission-bypass banner).
export function buildArgv(btn: ButtonDef, input?: string): string[] {
  const argv = ["-p", btn.command];

  if (btn.profile === "read-only") {
    argv.push("--allowedTools", ...READ_ONLY_ALLOWED_TOOLS);
  } else if (btn.profile === "bypass") {
    argv.push("--dangerously-skip-permissions");
  }

  if (input !== undefined) {
    if (input.startsWith("-")) {
      throw new Error(`buildArgv: input must not start with '-' (got: ${input})`);
    }
    argv.push("--", input);
  }

  return argv;
}
