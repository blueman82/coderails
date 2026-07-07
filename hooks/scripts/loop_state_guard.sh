#!/bin/bash
# Stop hook — when an agentic loop is active in this session, block (exit 2) unless
# a session-owned progress.json exists at the resolved path. Enforces PRESENCE +
# OWNERSHIP only; it does NOT police content freshness (that's the anti-stall
# guard's job, below).
#
# Honest boundary (same as check_verify_loop.sh): this forces the file to exist and
# be this session's; it cannot force the content to be accurate.
#
# Shared loop-detection (invocation count, path, file state) lives in
# lib/loop_state_common.sh, sourced below and shared with loop_stall_guard.sh, which
# enforces the anti-stall LOOP-STOP declaration.
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
[ -z "$cwd" ] && cwd="$PWD"  # Falls back to $PWD when .cwd is absent.
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

gate_loop_evals_required() {
  # Must run BEFORE als_gate_loop_complete: that shared function exits 0
  # directly (not just "returns") the instant status=complete, not re-armed,
  # and session-owned — it IS the off-switch, so calling this gate after it
  # would never be reached on exactly the path this gate needs to intercept.
  # Re-check the same three conditions explicitly here since
  # als_gate_loop_complete has no way to signal "checked, still active" back
  # to a caller placed after it.
  if [ "$ALS_STATUS" = "complete" ] && [ "$ALS_REARMED" -eq 0 ] && [ "$ALS_SESSION" = "$session_id" ]; then
    als_read_work_units "$ALS_PATH"
    if [ "$ALS_WORK_UNIT_COUNT" -ge 3 ]; then
      local loop_dir; loop_dir=$(dirname "$ALS_PATH")
      als_read_loop_evals_result "$loop_dir"
      case "$ALS_LOOP_EVALS_RESULT" in
        GO|TIER0)
          als_log "hook=loop_state_guard session=$session_id work_units=$ALS_WORK_UNIT_COUNT evals=$ALS_LOOP_EVALS_RESULT blocked=0"
          ;;
        NO-GO|ABSENT)
          als_log "hook=loop_state_guard session=$session_id work_units=$ALS_WORK_UNIT_COUNT evals=$ALS_LOOP_EVALS_RESULT blocked=1"
          echo "[loop-state-guard] Loop complete with $ALS_WORK_UNIT_COUNT work-units, but no passing loop-scope evals.json found at:
  $loop_dir/evals.json
Generate loop-scope evals via /coderails:task-evals (or a justified tier-0 exemption) and grade them GO before declaring complete." >&2
          exit 2
          ;;
        UNJUSTIFIED)
          als_log "hook=loop_state_guard session=$session_id work_units=$ALS_WORK_UNIT_COUNT evals=$ALS_LOOP_EVALS_RESULT blocked=1"
          echo "[loop-state-guard] Loop complete with $ALS_WORK_UNIT_COUNT work-units, and evals.json at:
  $loop_dir/evals.json
grades GO/TIER0 but is missing a non-blank tier_justification. Add a tier_justification (at tier 0: why the exemption is legitimate; at tier 1/2: which tier predicate fired) before declaring complete." >&2
          exit 2
          ;;
        *)
          als_log "hook=loop_state_guard session=$session_id work_units=$ALS_WORK_UNIT_COUNT evals=$ALS_LOOP_EVALS_RESULT blocked=1 reason=unrecognised_evals_result"
          echo "[loop-state-guard] Loop complete with $ALS_WORK_UNIT_COUNT work-units, but evals.json at:
  $loop_dir/evals.json
produced an unrecognised result ('$ALS_LOOP_EVALS_RESULT') from als_read_loop_evals_result. Fail-closed: treating this as a block. Inspect the file and regenerate it via /coderails:task-evals." >&2
          exit 2
          ;;
      esac
    else
      als_log "hook=loop_state_guard session=$session_id work_units=$ALS_WORK_UNIT_COUNT evals=skipped-below-threshold blocked=0"
    fi
  fi
}

als_gate_no_transcript "$transcript"
als_gate_stop_loop "$stop_hook_active"
als_gate_require_active_loop "$transcript" "loop_state_guard" "$session_id"
als_load_progress "$cwd" "$session_id"
gate_loop_evals_required
als_gate_loop_complete "loop_state_guard" "$session_id"
gate_present_and_owned
block_state_failure
