#!/bin/bash
# Two-event crack-on gate: while a "crack on" envelope is active in a session,
# asking the human anything (the AskUserQuestion tool) is mechanically denied.
#
#   UserPromptSubmit — detect "crack on" (case-insensitive, word-boundary) in
#     the RAW submitted prompt (payload .prompt) and stamp a per-session
#     crack_on_active flag file. Detection deliberately never reads the
#     transcript or any injected context: the phrase "crack on" appears in the
#     agentic-loop skill body and in injected memory in essentially every
#     session, so a transcript/context scan would false-positive fleet-wide
#     and permanently suppress human interaction. Only the human actually
#     typing the phrase activates the gate.
#   PreToolUse (AskUserQuestion) — if this session's flag is stamped, deny via
#     permissionDecision JSON (never exit 2). Scoped to AskUserQuestion only:
#     the agentic-loop hard-stops are turn-ending LOOP-STOP declarations, not
#     AskUserQuestion calls, so they are untouched by design.
#
# The flag lives beside the session's progress.json path: lib/agentic_loop_path.sh
# is the sole authority for the session+repo key (worktree hops resolve to the
# same key as their primary checkout). No session_id in the payload -> the gate
# stands aside entirely (an unkeyable stamp could never be found again).

IFS= read -r -d '' -t 5 input || true

event=$(echo "$input" | jq -r '.hook_event_name // empty')
session_id=$(echo "$input" | jq -r '.session_id // empty')
cwd=$(echo "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd="$PWD"

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# flag_path: prints the session+repo-keyed flag file path, empty on failure.
# dirname of the helper's progress.json path IS the session+repo key dir.
flag_path() {
  local p
  p=$(bash "$SCRIPT_DIR/lib/agentic_loop_path.sh" "$cwd" "$session_id" 2>/dev/null)
  [ -z "$p" ] && return 1
  printf '%s/crack_on_active' "$(dirname "$p")"
}

# ── UserPromptSubmit: stamp on a raw-prompt match ──────────────────────────
if [ "$event" = "UserPromptSubmit" ]; then
  [ -z "$session_id" ] && exit 0
  prompt=$(echo "$input" | jq -r '.prompt // empty')
  [ -z "$prompt" ] && exit 0
  # Word-boundary match: "crack" and "on" as whole words, any whitespace run
  # between them. [^[:alnum:]] boundaries instead of \b for BSD/GNU grep parity.
  if printf '%s' "$prompt" | grep -qiE '(^|[^[:alnum:]])crack[[:space:]]+on([^[:alnum:]]|$)'; then
    flag=$(flag_path) || exit 0
    [ -z "$flag" ] && exit 0
    mkdir -p "$(dirname "$flag")" 2>/dev/null
    date -Iseconds > "$flag" 2>/dev/null
    log_line "hook=crack_on_gate event=UserPromptSubmit session=$session_id stamped=1"
  fi
  exit 0
fi

# ── PreToolUse: deny AskUserQuestion while the flag is stamped ─────────────
if [ "$event" = "PreToolUse" ]; then
  tool_name=$(echo "$input" | jq -r '.tool_name // empty')
  [ "$tool_name" = "AskUserQuestion" ] || exit 0
  [ -z "$session_id" ] && exit 0
  flag=$(flag_path) || exit 0
  if [ -n "$flag" ] && [ -f "$flag" ]; then
    log_line "hook=crack_on_gate event=PreToolUse session=$session_id tool=AskUserQuestion denied=1"
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "crack-on active: human-ask suppressed; proceed autonomously. A crack-on envelope was activated by the user in this session, so AskUserQuestion is mechanically denied — make the call yourself using the envelope scope, or end the turn with a report if genuinely outside it."
      }
    }'
    exit 0
  fi
  exit 0
fi

exit 0
