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

IFS= read -r -d '' -t 5 input || true
# If jq is absent, this extraction silently yields empty, transcript stays "",
# and als_gate_no_transcript below allows the stop — fail-open is relied on here,
# not just an accident of the missing-transcript path.
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(als_sanitise_session_id "$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)

# Extract the last assistant text, retrying for the transcript-flush race
# (same approach as check_verify_loop.sh). Keep as a local helper — not shared
# with loop_state_guard.sh (dedup is out of scope for this refactor).
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

# Best-effort jq read-modify-write of progress.json's loop_stop_counts.<category>.
# Sole writer of this field (hook-owned; the orchestrator must never write it).
# Never fails the stop: any missing file, malformed JSON, or mv failure is logged
# and swallowed — declaring the stop matters more than the counter write succeeding.
bump_loop_stop_count() {
  local category="$1"
  command -v jq >/dev/null 2>&1 || return 0
  [ -n "$ALS_PATH" ] && [ -f "$ALS_PATH" ] || return 0
  local tmp="${ALS_PATH}.tmp"
  if jq --arg cat "$category" \
        '.loop_stop_counts[$cat] = ((.loop_stop_counts[$cat] // 0) + 1)' \
        "$ALS_PATH" > "$tmp" 2>/dev/null; then
    mv "$tmp" "$ALS_PATH" 2>/dev/null || { rm -f "$tmp" 2>/dev/null; als_log "hook=loop_stall_guard session=$session_id counter_write=mv_failed category=$category"; }
  else
    rm -f "$tmp" 2>/dev/null
    als_log "hook=loop_stall_guard session=$session_id counter_write=jq_failed category=$category"
  fi
}

gate_loop_stop_declared() {
  # Retry the extract for the transcript-flush race until the length stabilises.
  prev_len=-1; attempts=0; text=""
  while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
    text=$(extract_last_text); cur_len=${#text}
    if [ "$cur_len" -eq "$prev_len" ] && [ "$cur_len" -gt 0 ]; then break; fi
    prev_len=$cur_len
    attempts=$((attempts + 1))
    [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
  done
  # The regex is built from the single-source vocab; the category must be followed
  # by a non-alphanumeric char or end-of-line so "completed" does not match "complete".
  if printf '%s\n' "$text" | grep -qiE "^[[:space:]]*LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})([^[:alnum:]]|$)"; then
    # If the message carries more than one LOOP-STOP line, `tail -1` counts the
    # LAST one. This is intentional, not incidental: SKILL.md defines the
    # declaration as the turn's ENDING line ("End the stopping turn with:"), so
    # only the final declaration reflects the turn's actual outcome.
    category=$(printf '%s\n' "$text" | grep -oiE "LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})" | grep -oiE "(${LOOP_STOP_VOCAB})\$" | tail -1)
    bump_loop_stop_count "$category"
    als_log "hook=loop_stall_guard session=$session_id invocations=$ALS_INVOCATIONS declared=1 blocked=0"
    exit 0
  fi
}

block_missing_declaration() {
  als_log "hook=loop_stall_guard session=$session_id invocations=$ALS_INVOCATIONS declared=0 blocked=1"
  echo "[loop-stall-guard] Active agentic loop, no LOOP-STOP declaration in your last message.
Continue the loop, OR declare your stop by ending your message with a line:
  LOOP-STOP: <${LOOP_STOP_VOCAB}> — <reason>
Declaring \`complete\` means the loop is done: also set progress.json status to
\"complete\" and run the Phase 13 self-audit." >&2
  exit 2
}

als_gate_no_transcript "$transcript"
als_gate_stop_loop "$stop_hook_active"
als_gate_require_active_loop "$transcript" "loop_stall_guard" "$session_id"
als_load_progress "$cwd" "$session_id"
als_gate_loop_complete "loop_stall_guard" "$session_id"
gate_loop_stop_declared
block_missing_declaration
