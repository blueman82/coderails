#!/bin/bash
# loop_state_common.sh — shared detection for the agentic-loop Stop guards.
# SOURCED (not executed) by loop_state_guard.sh (C1, presence/ownership) and
# loop_stall_guard.sh (C2, anti-stall). Single source for: env defaults, the
# discipline-log helper, the LOOP-STOP vocabulary, and the active-loop /
# progress.json state resolution — so the two guards can never drift on what
# "an active loop" means.

# Single source of truth for the LOOP-STOP category vocabulary (C2). The C2 guard
# builds BOTH its match regex and its block message from this, so they can't disagree.
LOOP_STOP_VOCAB="hard-stop|approval-gate|awaiting-input|complete"

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

# Append a single key=value line to the discipline log (best-effort).
als_log() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

# Sanitise a session_id extracted from the Stop-hook JSON payload. If the
# payload's session_id is missing/null, the jq extraction below falls back to
# the literal "?" — a FIXED sentinel that would make every malformed-payload
# session collide onto the identical progress.json path, silently defeating
# session-scoped isolation. Same fallback style as agentic_loop_path.sh's own
# default: generate a fresh unique value (PID + high-res timestamp) instead of
# a shared constant, so two concurrent malformed-payload sessions can't collide.
als_sanitise_session_id() {
  local raw="$1"
  if [ -z "$raw" ] || [ "$raw" = "?" ]; then
    printf 'unknown-%s-%s' "$$" "$(date +%s%N 2>/dev/null || date +%s)"
  else
    printf '%s' "$raw"
  fi
}

# Count agentic-loop Skill invocations across the WHOLE transcript (one-shot).
# Structured jq match on a tool_use — never a text grep. Matches the scoped
# ("coderails:agentic-loop") and bare ("agentic-loop") skill names.
als_count_invocations() {
  jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use" and .name == "Skill")
      | (.input.skill // "")
      | select(test("(^|:)agentic-loop$")) ]
    | length
  ' "$1" 2>/dev/null
}

# Stable invocation count: retry for the transcript-flush race until it settles.
als_stable_invocations() {
  local transcript="$1" prev=-1 attempts=0 n=0
  while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
    n=$(als_count_invocations "$transcript"); [ -z "$n" ] && n=0
    if [ "$n" -eq "$prev" ]; then break; fi
    prev=$n
    attempts=$((attempts + 1))
    [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
  done
  printf '%s' "$n"
}

# Resolve the progress.json path via the sole path authority (sibling script).
als_resolve_path() { bash "$(dirname "${BASH_SOURCE[0]}")/agentic_loop_path.sh" "$1" "$2" 2>/dev/null; }

# Read progress.json state into globals ALS_STATUS / ALS_SESSION / ALS_MARKER.
# ALS_MARKER is sanitised to a non-negative integer (empty/non-numeric -> 0).
als_read_file_state() {
  ALS_STATUS=""; ALS_SESSION=""; ALS_MARKER=0
  if [ -n "$1" ] && [ -f "$1" ]; then
    ALS_STATUS=$(jq -r '.status // ""' "$1" 2>/dev/null)
    ALS_SESSION=$(jq -r '.session_id // ""' "$1" 2>/dev/null)
    ALS_MARKER=$(jq -r '.completed_marker // 0' "$1" 2>/dev/null)
    case "$ALS_MARKER" in (''|*[!0-9]*) ALS_MARKER=0;; esac
  fi
}

# ── Shared gate functions (called by both loop guards) ───────────────────────
# Guard scripts do NOT use set -euo pipefail; gate functions exit directly to
# skip or block, exactly like require::* helpers in scripts/lib/git-common.sh.

# Gate: skip if no transcript file to inspect.
als_gate_no_transcript() {
  local transcript="$1"
  if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
    exit 0
  fi
}

# Gate: skip if already blocked this turn to avoid a stop-loop.
als_gate_stop_loop() {
  local stop_hook_active="$1"
  if [ "$stop_hook_active" = "true" ]; then
    exit 0
  fi
}

# Gate: skip if no agentic-loop Skill invocation found — not a loop.
# Sets global ALS_INVOCATIONS. Logs and exits when invocations = 0.
# Takes hook name as arg so the log line carries the correct hook= tag.
als_gate_require_active_loop() {
  local transcript="$1" hook="$2" session="$3"
  ALS_INVOCATIONS=$(als_stable_invocations "$transcript"); [ -z "$ALS_INVOCATIONS" ] && ALS_INVOCATIONS=0
  if [ "$ALS_INVOCATIONS" -eq 0 ]; then
    als_log "hook=$hook session=$session invocations=0 active=0 blocked=0"
    exit 0
  fi
}

# Setup: resolve progress.json path and read its state into globals.
# Sets ALS_PATH, ALS_STATUS, ALS_SESSION, ALS_MARKER, ALS_REARMED.
# Requires ALS_INVOCATIONS to be set (by als_gate_require_active_loop).
als_load_progress() {
  local cwd="$1" session="$2"
  ALS_PATH=$(als_resolve_path "$cwd" "$session")
  als_read_file_state "$ALS_PATH"
  ALS_REARMED=0
  if [ "$ALS_INVOCATIONS" -gt "$ALS_MARKER" ]; then ALS_REARMED=1; fi
}

# Gate: skip when the loop is genuinely complete — complete, not re-armed, and
# session-owned (the shared off-switch). Logs and exits 0.
# Takes hook name as arg so the log line carries the correct hook= tag.
als_gate_loop_complete() {
  local hook="$1" session="$2"
  if [ "$ALS_STATUS" = "complete" ] && [ "$ALS_REARMED" -eq 0 ] && [ "$ALS_SESSION" = "$session" ]; then
    als_log "hook=$hook session=$session invocations=$ALS_INVOCATIONS status=complete rearmed=0 owned=1 blocked=0"
    exit 0
  fi
}
