#!/bin/bash
# Stop hook — when an agentic loop is active in this session, block (exit 2) unless
# a session-owned progress.json exists at the resolved path. Enforces PRESENCE +
# OWNERSHIP only; it does NOT police content freshness (that is Spec C2's job).
#
# Honest boundary (same as check_verify_loop.sh): this forces the file to exist and
# be this session's; it cannot force the content to be accurate.
#
# Gates run top to bottom; the first that matches decides. Cheapest skips first.
#   skip  — no transcript                                       → allow
#   skip  — already blocked once this turn (loop-guard)         → allow
#   skip  — no agentic-loop Skill invocation in the transcript  → allow (not a loop)
#   skip  — file complete, not re-armed, session-owned          → allow (loop done)
#   skip  — file present, session-owned, not complete           → allow (presence ok)
#   BLOCK — file absent / session mismatch / stale-complete-after-rearm

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

input=$(cat)
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)

# Gate 1 — no transcript to inspect.
if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
  exit 0
fi

# Gate 2 — already blocked once this turn; allow to avoid a stop-loop.
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

# Count agentic-loop Skill invocations across the WHOLE transcript. Recency
# (re-arm detection) needs the full history, so this does not tail. Structured
# jq match on a tool_use — never a text grep. Matches both the scoped name
# ("coderails:agentic-loop") and the bare ("agentic-loop"). Retry for the
# transcript-flush race until the count stabilises, as check_verify_loop does.
count_invocations() {
  jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use" and .name == "Skill")
      | (.input.skill // "")
      | select(test("(^|:)agentic-loop$")) ]
    | length
  ' "$transcript" 2>/dev/null
}

prev=-1; attempts=0; invocations=0
while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
  invocations=$(count_invocations); [ -z "$invocations" ] && invocations=0
  if [ "$invocations" -eq "$prev" ]; then break; fi
  prev=$invocations
  attempts=$((attempts + 1))
  [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
done

# Gate 3 — not a loop: the opt-in marker is absent. No discipline in force.
if [ "$invocations" -eq 0 ]; then
  log_line "hook=loop_state_guard session=$session_id invocations=0 active=0 blocked=0"
  exit 0
fi

# Resolve the path — the hook is the sole path authority. Use the payload cwd
# (the project dir), falling back to the hook process PWD.
path=$(bash "$(dirname "$0")/lib/agentic_loop_path.sh" "$cwd" 2>/dev/null)

# Read file state (empty/0 when absent).
file_status=""; file_session=""; completed_marker=0
if [ -n "$path" ] && [ -f "$path" ]; then
  file_status=$(jq -r '.status // ""' "$path" 2>/dev/null)
  file_session=$(jq -r '.session_id // ""' "$path" 2>/dev/null)
  completed_marker=$(jq -r '.completed_marker // 0' "$path" 2>/dev/null)
  case "$completed_marker" in (''|*[!0-9]*) completed_marker=0;; esac
fi

# Re-armed = a new loop invocation occurred after the recorded completion. Because
# the skill is invoked once per loop, the transcript invocation count equals the
# loop ordinal, which the orchestrator records as completed_marker at teardown.
rearmed=0
if [ "$invocations" -gt "$completed_marker" ]; then rearmed=1; fi

# Gate 4 — genuinely complete: complete, NOT re-armed, and session-owned. (Ownership
# is required so another session's completed file never silences this session's loop.)
if [ "$file_status" = "complete" ] && [ "$rearmed" -eq 0 ] && [ "$file_session" = "$session_id" ]; then
  log_line "hook=loop_state_guard session=$session_id invocations=$invocations status=complete rearmed=0 owned=1 blocked=0"
  exit 0
fi

# Gate 5 — present, session-owned, and active (not complete).
if [ -n "$path" ] && [ -f "$path" ] && [ "$file_session" = "$session_id" ] && [ "$file_status" != "complete" ]; then
  log_line "hook=loop_state_guard session=$session_id invocations=$invocations status=$file_status owned=1 blocked=0"
  exit 0
fi

# Gate 6 — BLOCK. Distinguish the three failure shapes.
stub_schema='{ "schema_version": 1, "session_id": "<this-session-id>", "status": "initialising", "created": "<ISO8601>", "authorising_prompt_raw": "<verbatim authorising prompt>", "completed_marker": 0 }'
if [ ! -f "$path" ]; then
  reason="absent"
  msg="[loop-state-guard] Agentic loop active but no progress.json found.
Create it at this exact path (copy it verbatim — never compute the path yourself):
  $path
with this stub, then enrich it as the loop progresses:
  $stub_schema"
elif [ "$file_session" != "$session_id" ]; then
  reason="session_mismatch"
  msg="[loop-state-guard] progress.json at:
  $path
belongs to session '$file_session', not this session ('$session_id').
Adopt this loop (re-stamp session_id to '$session_id'), or reinitialise the stub."
else
  reason="stale_complete_rearmed"
  msg="[loop-state-guard] A new agentic loop has started, but progress.json at:
  $path
still records the previous loop as complete. Re-initialise the stub for the new
loop (status back to \"initialising\"/\"in-progress\", carry completed_marker forward)
before stopping."
fi

log_line "hook=loop_state_guard session=$session_id invocations=$invocations status=${file_status:-absent} reason=$reason blocked=1"
echo "$msg" >&2
exit 2
