import type { ButtonDef } from "./config";

// Tools that only read state, never mutate the filesystem or run commands —
// safe for a read-only-profile button. Verified against `claude --help`
// 2026-07-06.
export const READ_ONLY_ALLOWED_TOOLS = ["Read", "Grep", "Glob"];

// buildArgv is THE single profile→flag mapping (per Task 7 brief) — Task 13
// must reuse this, never re-implement it.
//
// `input`, when given, is merged into a single prompt string with
// `btn.command` (space-separated), because the claude CLI's `-p`/`--print`
// takes exactly ONE positional prompt argument — confirmed empirically on
// this machine 2026-07-07: passing `btn.command` and `input` as two separate
// argv elements (e.g. `-p "/coderails:verify" -- "some claim"`) left
// `$ARGUMENTS` empty in the invoked slash command every time, because the
// CLI never merges a second positional into the prompt it already consumed.
// A single combined string (`-p -- "/coderails:verify some claim"`)
// delivers correctly — confirmed empirically the same day: `$ARGUMENTS` was
// populated and the CLI's plain single-prompt form
// (`claude -p "Reply with PONG"`, no command prefix) also replied correctly,
// which is why an empty `btn.command` (a free-text "ask" button) still works
// once `input` alone becomes the whole prompt.
//
// Two independent layers close the flag-smuggling vector (an input value
// like "--dangerously-skip-permissions" being parsed by the claude CLI as a
// real flag instead of literal prompt text, confirmed empirically on this
// machine 2026-07-06: `claude -p "--version"` prints the version banner and
// never answers the prompt, i.e. the CLI really does parse a leading-dash
// argument as a flag): (1) input starting with "-" is rejected outright
// (throws) rather than trusting the sentinel alone, checked against the raw
// input BEFORE it is merged into the combined prompt string; (2) a literal
// "--" end-of-options sentinel is inserted immediately before the combined
// prompt whenever input is present, confirmed empirically on this machine
// 2026-07-07 to still deliver correctly and to keep a flag-shaped substring
// embedded mid-prompt (e.g. "... ignore this --dangerously-skip-permissions
// in the middle") inert as literal text — no permission-bypass banner, model
// just answered the prompt.
function profileFlags(profile: ButtonDef["profile"]): string[] {
  if (profile === "read-only") return ["--allowedTools", ...READ_ONLY_ALLOWED_TOOLS];
  if (profile === "bypass") return ["--dangerously-skip-permissions"];
  return [];
}

export function buildArgv(btn: ButtonDef, input?: string): string[] {
  if (input === undefined) {
    if (btn.command.trim() === "") {
      throw new Error("buildArgv: refusing to spawn an empty prompt (no command and no input)");
    }
    return ["-p", btn.command, ...profileFlags(btn.profile)];
  }

  if (input.startsWith("-")) {
    throw new Error(`buildArgv: input must not start with '-' (got: ${input})`);
  }

  const prompt = btn.command ? `${btn.command} ${input}` : input;
  if (prompt.trim() === "") {
    throw new Error("buildArgv: refusing to spawn an empty prompt (no command and no input)");
  }

  return ["-p", ...profileFlags(btn.profile), "--", prompt];
}
