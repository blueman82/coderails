#!/bin/bash
# Stop hook — when an agentic loop is active in this session, block (exit 2) unless
# a session-owned progress.json exists at the resolved path. Enforces PRESENCE +
# OWNERSHIP only; it does NOT police content freshness (that is Spec C2's job).
#
# Honest boundary (same as check_verify_loop.sh): this forces the file to exist and
# be this session's; it cannot force the content to be accurate.
#
# Shared loop-detection (invocation count, path, file state) lives in
# lib/loop_state_common.sh, sourced below and shared with loop_stall_guard.sh (C2).
#
# Gates run top to bottom; the first that matches decides. Cheapest skips first.
#   skip  — no transcript                                       → allow
#   skip  — already blocked once this turn (loop-guard)         → allow
#   skip  — no agentic-loop Skill invocation in the transcript  → allow (not a loop)
#   skip  — file complete, not re-armed, session-owned          → allow (loop done)
#   skip  — file present, session-owned, not complete           → allow (presence ok)
#   BLOCK — file absent / session mismatch / stale-complete-after-rearm

. "$(dirname "$0")/lib/loop_state_common.sh"

IFS= read -r -d '' -t 5 input || true
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(als_sanitise_session_id "$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)

gate_present_and_owned() {
  if [ -n "$ALS_PATH" ] && [ -f "$ALS_PATH" ] && [ "$ALS_SESSION" = "$session_id" ] && [ "$ALS_STATUS" != "complete" ]; then
    als_log "hook=loop_state_guard session=$session_id invocations=$ALS_INVOCATIONS status=$ALS_STATUS owned=1 blocked=0"
    exit 0
  fi
}

block_state_failure() {
  stub_schema='{ "schema_version": 1, "session_id": "<this-session-id>", "status": "initialising", "created": "<ISO8601>", "authorising_prompt_raw": "<verbatim authorising prompt>", "completed_marker": 0 }'
  if [ ! -f "$ALS_PATH" ]; then
    reason="absent"
    msg="[loop-state-guard] Agentic loop active but no progress.json found.
Create it at this exact path (copy it verbatim — never compute the path yourself):
  $ALS_PATH
with this stub, then enrich it as the loop progresses:
  $stub_schema"
  elif [ "$ALS_SESSION" != "$session_id" ]; then
    reason="session_mismatch"
    msg="[loop-state-guard] progress.json at:
  $ALS_PATH
has session_id '$ALS_SESSION' recorded inside it, but this session is '$session_id'.
The path is already session-scoped, so this file should only ever be read by its
own session — this mismatch means the content was copied, hand-edited, or
corrupted. Re-stamp session_id to '$session_id' if you are knowingly adopting
this file, or reinitialise the stub."
  else
    reason="stale_complete_rearmed"
    msg="[loop-state-guard] A new agentic loop has started, but progress.json at:
  $ALS_PATH
still records the previous loop as complete. Re-initialise the stub for the new
loop (status back to \"initialising\"/\"in-progress\", carry completed_marker forward)
before stopping."
  fi
  als_log "hook=loop_state_guard session=$session_id invocations=$ALS_INVOCATIONS status=${ALS_STATUS:-absent} reason=$reason blocked=1"
  echo "$msg" >&2
  exit 2
}

als_gate_no_transcript "$transcript"
als_gate_stop_loop "$stop_hook_active"
als_gate_require_active_loop "$transcript" "loop_state_guard" "$session_id"
als_load_progress "$cwd" "$session_id"
als_gate_loop_complete "loop_state_guard" "$session_id"
gate_present_and_owned
block_state_failure
