#!/bin/bash
# Stop hook — anti-stall (C2). When an agentic loop is active and incomplete, block
# (exit 2) unless the stopping turn carries a valid LOOP-STOP declaration:
#   LOOP-STOP: <hard-stop|approval-gate|awaiting-input|complete> — <reason>
# Checks PRESENCE + a vocab CATEGORY only (honest boundary, same as check_verify_loop):
# it forces a categorised declaration, it cannot force the reason to be truthful.
#
# Shared loop-detection lives in lib/loop_state_common.sh (also used by C1's
# loop_state_guard.sh); the active-window decision is identical to C1's.
#
# Gates run top to bottom; the first that matches decides.
#   skip  — no transcript                                       → allow
#   skip  — already blocked once this turn (loop-guard)         → allow
#   skip  — no agentic-loop Skill invocation in the transcript  → allow (not a loop)
#   skip  — loop complete, not re-armed, session-owned          → allow (loop done)
#   skip  — last message carries a valid LOOP-STOP declaration  → allow (declared)
#   BLOCK — active + incomplete + no valid declaration

. "$(dirname "$0")/lib/loop_state_common.sh"

TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-300}"

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

invocations=$(als_stable_invocations "$transcript"); [ -z "$invocations" ] && invocations=0

# Gate 3 — not a loop: the opt-in marker is absent. No discipline in force.
if [ "$invocations" -eq 0 ]; then
  als_log "hook=loop_stall_guard session=$session_id invocations=0 active=0 blocked=0"
  exit 0
fi

# Resolve path + file state (shared with C1).
path=$(als_resolve_path "$cwd")
als_read_file_state "$path"
rearmed=0
if [ "$invocations" -gt "$ALS_MARKER" ]; then rearmed=1; fi

# Gate 4 — loop done (shared off-switch with C1): complete, not re-armed, owned.
if [ "$ALS_STATUS" = "complete" ] && [ "$rearmed" -eq 0 ] && [ "$ALS_SESSION" = "$session_id" ]; then
  als_log "hook=loop_stall_guard session=$session_id invocations=$invocations status=complete blocked=0"
  exit 0
fi

# Extract the last assistant text, retrying for the transcript-flush race
# (same approach as check_verify_loop.sh).
extract_last_text() {
  tail -n "$TAIL_LINES" "$transcript" 2>/dev/null | jq -s -r '
    [.[]?
     | select(.type == "assistant")
     | (.message.content
        | if type == "array" then [ .[]? | select(.type == "text") | .text ] | join(" ")
          elif type == "string" then .
          else "" end)
     | select(type == "string" and length > 0)]
    | last // ""
  ' 2>/dev/null
}
prev_len=-1; attempts=0; text=""
while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
  text=$(extract_last_text); cur_len=${#text}
  if [ "$cur_len" -eq "$prev_len" ] && [ "$cur_len" -gt 0 ]; then break; fi
  prev_len=$cur_len
  attempts=$((attempts + 1))
  [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
done

# Gate 5 — a valid LOOP-STOP declaration is present in the last message. The regex
# is built from the single-source vocab; the category must be followed by a
# non-alphanumeric char or end-of-line so "completed" does not match "complete".
if printf '%s\n' "$text" | grep -qiE "^[[:space:]]*LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})([^[:alnum:]]|$)"; then
  als_log "hook=loop_stall_guard session=$session_id invocations=$invocations declared=1 blocked=0"
  exit 0
fi

# Gate 6 — BLOCK. Hand back the exact tag template, built from the single-source vocab.
als_log "hook=loop_stall_guard session=$session_id invocations=$invocations declared=0 blocked=1"
echo "[loop-stall-guard] Active agentic loop, no LOOP-STOP declaration in your last message.
Continue the loop, OR declare your stop by ending your message with a line:
  LOOP-STOP: <${LOOP_STOP_VOCAB}> — <reason>
Declaring \`complete\` means the loop is done: also set progress.json status to
\"complete\" and run the Phase 13 self-audit." >&2
exit 2
