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
// argv elements (e.g. `-p "/coderails:cite-check" -- "some claim"`) left
// `$ARGUMENTS` empty in the invoked slash command every time, because the
// CLI never merges a second positional into the prompt it already consumed.
// A single combined string (`-p -- "/coderails:cite-check some claim"`)
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
// argument as a flag): (1) input starting with "-" (after trimming, so
// whitespace can't hide a leading dash from this check) is rejected
// outright (throws) rather than trusting the sentinel alone, checked
// BEFORE input is merged into the combined prompt string; (2) a literal
// "--" end-of-options sentinel is inserted immediately before the combined
// prompt whenever input is present, confirmed empirically on this machine
// 2026-07-07 to still deliver correctly and to keep a flag-shaped substring
// embedded mid-prompt (e.g. "... ignore this --dangerously-skip-permissions
// in the middle") inert as literal text — no permission-bypass banner, model
// just answered the prompt.
// "auto" is not a guarantee of tool access — confirmed empirically on this
// machine 2026-07-10: three consecutive `claude -p --permission-mode auto`
// runs against a web-search-requiring question succeeded once and fell back
// to "I don't have internet access" (no tool call attempted at all) twice,
// with no permission-block message in either failing run. This mirrors the
// same non-deterministic "does the model attempt the tool call" behavior
// already documented for the "standard" profile — "auto" changes what
// happens if a tool call is attempted and needs a permission decision
// (auto-approved rather than blocked waiting on an unanswerable headless
// prompt), it does not make the model reliably choose to attempt the call.
function profileFlags(profile: ButtonDef["profile"]): string[] {
  if (profile === "read-only") return ["--allowedTools", ...READ_ONLY_ALLOWED_TOOLS];
  if (profile === "bypass") return ["--dangerously-skip-permissions"];
  if (profile === "auto") return ["--permission-mode", "auto"];
  return [];
}

// Every dashboard-dispatched run is headless (`-p`, no human watching stdout)
// — confirmed by investigating a real failing run: the final assistant text
// ended with a live question addressed to a human ("Want me to archive those
// now, or leave for your review first?"), even though the run's own
// `--allowedTools` never included an interactive-question tool and no such
// tool-call appears in the transcript. The model wasn't blocked; it just
// wrote in a conversational, human-addressed style out of interactive-session
// habit. Prepending this framing to every constructed prompt — not just for
// memory-consolidation, but for every button/routine that flows through
// buildArgv — closes that gap at the one choke point rather than requiring
// every SKILL.md to opt in individually. Kept to a single line (no embedded
// newlines) so it can't alter argv shape; prepended to `prompt`/`btn.command`
// text, never assigned to `input`, so it can never touch the flag-smuggling
// check above (that check runs on `input` only).
const NON_INTERACTIVE_FRAMING =
  "This is an unattended, headless run with no human watching output in real time. " +
  "Do not address a human or end your final text with a question. " +
  "Write findings only to whatever report/artifact file the invoked skill specifies.";

export function buildArgv(btn: ButtonDef, rawInput?: string): string[] {
  // Normalise first: empty or whitespace-only input is treated exactly like
  // no input at all. route.ts does no trim/empty check of its own (only the
  // UI's call site converts empty→undefined before ever reaching here), so
  // a direct API caller can hand buildArgv input:"" or input:"   " — without
  // this normalisation that would still take the input-bearing branch below
  // and produce a merged prompt with a trailing space and a needless '--'
  // sentinel, instead of the same clean argv a genuine no-input press gets.
  const input = rawInput !== undefined && rawInput.trim() === "" ? undefined : rawInput;

  if (input === undefined) {
    if (btn.command.trim() === "") {
      throw new Error("buildArgv: refusing to spawn an empty prompt (no command and no input)");
    }
    return ["-p", `${NON_INTERACTIVE_FRAMING} ${btn.command}`, ...profileFlags(btn.profile)];
  }

  // Checked against the trimmed value so whitespace can't smuggle a flag
  // past a naive startsWith check (e.g. "  --dangerously-skip-permissions").
  // Checked BEFORE framing is prepended, and against raw `input` alone —
  // NON_INTERACTIVE_FRAMING is never assigned to `input`, so it can never
  // reach or influence this check.
  if (input.trim().startsWith("-")) {
    throw new Error(`buildArgv: input must not start with '-' (got: ${input})`);
  }

  const prompt = btn.command ? `${btn.command} ${input}` : input;

  return ["-p", ...profileFlags(btn.profile), "--", `${NON_INTERACTIVE_FRAMING} ${prompt}`];
}
